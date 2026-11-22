"""用固定留出批验收剧场来信的质心分流，成绩按规则版本分开计算。"""

import re
from collections import Counter
from math import fsum, isclose, log, sqrt
from unicodedata import normalize

from .rules import display, find_overlap, moment, resolve, sort_key
from .spec import MANUAL_QUEUE, QUEUES, SPEC


_TOKEN_RUNS = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+|[a-z0-9]+")
_PREDICTION_COLUMNS = (
    ("ticket_id", "留出来信编号"), ("arrived_at", "到件时间"), ("actual", "人工归口"),
    ("rule_version", "采用规则"), ("candidate", "最接近的训练队列"),
    ("predicted", "分流去向"), ("similarity", "最高余弦分"), ("matched_terms", "命中词数"),
    ("outcome", "分流判定"), ("reason", "拒绝原因"), ("batch_total", "同批次总分"),
    ("baseline", "多数类去向"),
)
_SCORE_COLUMNS = (
    ("rule_version", "规则版本"), ("effective_at", "生效时刻"), ("issued_seq", "签发序号"),
    ("threshold", "最低相似度"), ("letters", "留出件数"), ("macro_f1", "分流宏 F1"),
    ("baseline_f1", "多数类宏 F1"), ("delta", "宏 F1 差值"), ("coverage", "自动分流覆盖率"),
    ("manual", "人工分诊"), ("wrong", "错投"),
)
_QUEUE_COLUMNS = (
    ("queue", "队列"), ("training", "训练件数"), ("support", "留出归口量"),
    ("routed", "预计接件量"), ("correct", "正确分流"), ("precision", "精确率"),
    ("recall", "召回率"), ("f1", "F1"), ("baseline_f1", "基线 F1"),
    ("top_terms", "质心代表词"), ("handling", "接件说明"),
)


def validate_rows(rows):
    """校验 CSV 来信格式、到件时刻和编号唯一性，返回规范化副本。"""
    if not isinstance(rows, (list, tuple)) or not rows:
        raise ValueError("来信明细为空，请按样例导入带归口和批次的记录。")
    tickets = []
    seen = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"第 {index} 条来信格式有误。")
        ticket = {}
        for field in SPEC["fields"]:
            key = field["key"]
            value = row.get(key)
            value = value.strip() if isinstance(value, str) else ""
            if not value or len(value) > field.get("max_length", 300):
                raise ValueError(f"第 {index} 条来信的「{field['label']}」缺失或长度超限。")
            if field["type"] == "select" and value not in field["options"]:
                raise ValueError(f"第 {index} 条来信的「{field['label']}」须为：{'、'.join(field['options'])}。")
            ticket[key] = value
        try:
            moment(ticket["arrived_at"])
        except ValueError:
            raise ValueError(f"第 {index} 条来信的「到件时间」格式不正确。") from None
        identifier = normalize("NFKC", ticket["ticket_id"]).casefold()
        if identifier in seen:
            raise ValueError(f"来信编号「{ticket['ticket_id']}」重复，同一编号只能出现于一个批次。")
        seen.add(identifier)
        tickets.append(ticket)
    return tickets


def _counts(text):
    tokens = Counter()
    for run in _TOKEN_RUNS.findall(normalize("NFKC", text).casefold()):
        if run.isascii() or len(run) == 1:
            tokens[run] += 1
        else:
            tokens.update(run[index:index + 2] for index in range(len(run) - 1))
    return tokens


def _unit(vector):
    norm = sqrt(fsum(value * value for value in vector.values()))
    return {term: value / norm for term, value in vector.items()} if norm else {}


def _vector(counts, idf):
    return _unit({term: count * idf[term] for term, count in counts.items() if term in idf})


def _fit(training, label_counts, max_terms):
    documents = [_counts(ticket["text"]) for ticket in training]
    frequency = Counter(term for document in documents for term in document)
    if not frequency:
        raise ValueError("训练批提取不到有效词，请补录含汉字、字母或数字的来信。")
    terms = sorted(frequency, key=lambda term: (-frequency[term], term))
    idf = {
        term: 1 + log((1 + len(training)) / (1 + frequency[term]))
        for term in terms[:max_terms or None]
    }
    sums = {label: Counter() for label in label_counts}
    for ticket, document in zip(training, documents):
        sums[ticket["label"]].update(_vector(document, idf))
    centroids = {
        label: {term: weight / label_counts[label] for term, weight in weights.items()}
        for label, weights in sums.items()
    }
    return idf, centroids


def _prediction(ticket, idf, directions, threshold, majority):
    vector = _vector(_counts(ticket["text"]), idf)
    scores = {
        label: min(1.0, fsum(weight * direction.get(term, 0.0) for term, weight in vector.items()))
        for label, direction in directions.items()
    }
    best = max(scores.values())
    leaders = sorted(
        label for label, score in scores.items() if isclose(score, best, rel_tol=0, abs_tol=1e-12)
    )
    actual = ticket["label"]
    predicted = MANUAL_QUEUE
    candidate = " / ".join(leaders) if best else ""
    if not vector:
        reason = "无训练词表命中"
    elif len(leaders) > 1:
        reason = "最高余弦分并列"
    elif best < threshold and not isclose(best, threshold, rel_tol=0, abs_tol=1e-12):
        reason = "最高余弦分低于阈值"
    else:
        predicted = leaders[0]
        reason = "最高余弦分达到阈值"
    if predicted == MANUAL_QUEUE:
        outcome = "转人工"
    else:
        outcome = "命中" if predicted == actual else "错投"
    return {
        "ticket_id": ticket["ticket_id"], "arrived_at": display(ticket["arrived_at"]), "actual": actual,
        "candidate": candidate, "predicted": predicted, "similarity": round(best, 6),
        "matched_terms": len(vector), "outcome": outcome, "reason": reason, "baseline": majority,
    }


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else 0.0


def _table(title, columns, rows):
    return {"title": title, "columns": [{"key": key, "label": label} for key, label in columns], "rows": rows}


def _queue_summary(labels, counts, centroids, predictions, majority):
    support = Counter(row["actual"] for row in predictions)
    routed = Counter(row["predicted"] for row in predictions)
    correct = Counter(row["actual"] for row in predictions if row["outcome"] == "命中")
    total = len(predictions)
    rows = []
    model_scores = []
    baseline_scores = []
    for label in labels:
        f1 = _ratio(2 * correct[label], support[label] + routed[label])
        baseline_f1 = _ratio(2 * support[label], support[label] + total) if label == majority else 0.0
        model_scores.append(f1)
        baseline_scores.append(baseline_f1)
        centroid = centroids.get(label, {})
        top_terms = sorted(centroid, key=lambda term: (-centroid[term], term))[:6]
        handling = QUEUES[label]
        if not centroid:
            handling += " 当前训练词表下无可用质心，请补充训练件或扩大词表。"
        rows.append({
            "queue": label, "training": counts[label], "support": support[label], "routed": routed[label],
            "correct": correct[label], "precision": round(_ratio(correct[label], routed[label]), 6),
            "recall": round(_ratio(correct[label], support[label]), 6),
            "f1": round(f1, 6), "baseline_f1": round(baseline_f1, 6),
            "top_terms": "、".join(top_terms), "handling": handling,
        })
    rows.append({
        "queue": MANUAL_QUEUE, "training": None, "support": None, "routed": routed[MANUAL_QUEUE],
        "correct": None, "precision": None, "recall": None, "f1": None, "baseline_f1": None,
        "top_terms": "", "handling": "值班客服先确认来件诉求，再转交对应业务组。",
    })
    return rows, fsum(model_scores) / len(labels), fsum(baseline_scores) / len(labels)


def _check_snapshot(snapshot):
    if not isinstance(snapshot, (list, tuple)) or not snapshot:
        raise ValueError("本次运行没有冻结的规则快照，无法验收，请重新提交。")
    versions = []
    for item in snapshot:
        if not isinstance(item, dict) or not item.get("version") or not isinstance(item.get("params"), dict):
            raise ValueError("规则快照内容不完整，请重新提交验收。")
        params = item["params"]
        max_terms, threshold = params.get("max_terms"), params.get("min_similarity")
        if (type(max_terms) is not int or not 0 <= max_terms <= 10000
                or type(threshold) not in (int, float) or not 0 <= threshold <= 1):
            raise ValueError(f"规则版本「{item['version']}」的参数超出验收口径。")
        versions.append(item)
    overlap = find_overlap(versions)
    if overlap:
        stamp, seq = overlap
        raise ValueError(f"规则快照在 {stamp.isoformat()} 以签发序号 {seq} 版本重叠，无法确定唯一生效版本。")
    return sorted(versions, key=sort_key)


def _group_holdout(holdout, versions):
    """按到件时刻为每封留出件取当时生效的规则版本，同版本归为一批。"""
    groups = {}
    for ticket in holdout:
        version = resolve(versions, ticket["arrived_at"])
        if version is None:
            raise ValueError(
                f"来信「{ticket['ticket_id']}」到件时刻 {ticket['arrived_at']} 在规则快照中没有生效版本，"
                "请补齐规则后重新导入验收。")
        groups.setdefault(version["version"], {"version": version, "tickets": []})["tickets"].append(ticket)
    return [groups[key] for key in sorted(groups, key=lambda key: sort_key(groups[key]["version"]))]


def analyze(rows, rule_snapshot):
    tickets = sorted(validate_rows(rows), key=lambda ticket: ticket["ticket_id"])
    versions = _check_snapshot(rule_snapshot)
    training = [ticket for ticket in tickets if ticket["split"] == "train"]
    holdout = [ticket for ticket in tickets if ticket["split"] == "test"]
    if not training or not holdout:
        raise ValueError("必须同时提供 train 训练件和 test 留出件，批次以导入标记为准。")
    counts = Counter(ticket["label"] for ticket in training)
    if len(counts) < 2:
        raise ValueError("训练批至少需要两个已标注队列，才能验收分流。")
    majority = min(counts, key=lambda label: (-counts[label], label))
    groups = _group_holdout(holdout, versions)

    fits = {}
    score_rows = []
    predictions = []
    tables = []
    charts = []
    metrics = []
    for group in groups:
        version = group["version"]
        params = version["params"]
        max_terms = params["max_terms"]
        if max_terms not in fits:
            idf, centroids = _fit(training, counts, max_terms)
            fits[max_terms] = (idf, {label: _unit(centroid) for label, centroid in centroids.items()}, centroids)
        idf, directions, centroids = fits[max_terms]
        batch = [
            {**_prediction(ticket, idf, directions, params["min_similarity"], majority),
             "rule_version": version["version"]}
            for ticket in group["tickets"]
        ]
        labels = sorted(counts.keys() | {ticket["label"] for ticket in group["tickets"]})
        queues, macro_f1, baseline_f1 = _queue_summary(labels, counts, centroids, batch, majority)
        outcomes = Counter(row["outcome"] for row in batch)
        manual = outcomes["转人工"]
        wrong = outcomes["错投"]
        total = len(batch)
        coverage = (total - manual) / total
        delta = macro_f1 - baseline_f1
        for row in batch:
            row["batch_total"] = round(macro_f1, 6)
        predictions.extend(batch)
        score_rows.append({
            "rule_version": version["version"], "effective_at": display(version["effective_at"]),
            "issued_seq": version["issued_seq"], "threshold": params["min_similarity"],
            "letters": total, "macro_f1": round(macro_f1, 6), "baseline_f1": round(baseline_f1, 6),
            "delta": round(delta, 6), "coverage": f"{coverage:.1%}",
            "manual": manual, "wrong": wrong,
        })
        metrics.extend([
            {"label": f"分流宏 F1 · {version['version']}", "value": round(macro_f1, 6),
             "detail": f"{len(labels)} 个队列等权平均，同批次 {total} 封"},
            {"label": f"多数类宏 F1 · {version['version']}", "value": round(baseline_f1, 6),
             "detail": f"训练批多数队列为{majority}（{counts[majority]} 封）"},
            {"label": f"自动分流覆盖率 · {version['version']}", "value": f"{coverage:.1%}",
             "detail": f"{total - manual}/{total} 封进入业务队列，人工分诊 {manual} 封"},
        ])
        tables.append(_table(f"队列负载与验收指标 · {version['version']}", _QUEUE_COLUMNS, queues))
        charts.append({
            "title": f"留出来信的预计队列接件量 · {version['version']}", "kind": "bar",
            "series": [{"label": row["queue"], "value": row["routed"]} for row in queues],
        })

    outcomes = Counter(row["outcome"] for row in predictions)
    manual = outcomes["转人工"]
    wrong = outcomes["错投"]
    total = len(holdout)
    names = "、".join(row["rule_version"] for row in score_rows)
    state = "warning" if manual or wrong or any(row["delta"] <= 0 for row in score_rows) else "ok"
    return {
        "state": state,
        "headline": (
            f"留出 {total} 封按 {len(score_rows)} 个规则版本分别计分："
            f"自动分流 {total - manual} 封（错投 {wrong} 封），人工分诊 {manual} 封。"
        ),
        "note": (
            f"训练 {len(training)} 封，开跑时冻结 {len(versions)} 个已发布规则版本，本批采用 {names}。"
            "各版本成绩分开核对，不合并成一份成绩；多数类基线全部投向"
            f"{majority}。"
        ),
        "metrics": metrics,
        "tables": [
            _table("逐件分流明细", _PREDICTION_COLUMNS, predictions),
            _table("规则批次成绩", _SCORE_COLUMNS, score_rows),
            *tables,
        ],
        "charts": charts,
        "sections": [{
            "title": "规则版本与排班",
            "text": (
                "每封留出件按到件时刻采用当时生效的规则版本，同一生效时刻的变更按签发序号取唯一版本。"
                "验收中途发布的规则不影响本次快照，补到的迟到记录另起验收仍沿用各自开跑时的快照，重跑不重复计分。"
                "预计接件量汇总模型去向，人工归口量汇总留出标签；结合逐件依据复核错投和分诊原因。"
            ),
        }],
    }
