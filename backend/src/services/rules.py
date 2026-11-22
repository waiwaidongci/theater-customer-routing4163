"""分流规则版本登记处：发布、快照与导入批次的规则覆盖校验。"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from src.domain.rules import find_overlap, resolve, sort_key
from src.models.rules import RuleVersion
from src.services.audit import record
from src.services.validation import normalize_params
from src.utils.time import iso


def as_dict(item):
    return {'version': item.version, 'effective_at': iso(item.effective_at),
            'issued_seq': item.issued_seq, 'params': item.params,
            'author': item.author, 'created_at': iso(item.created_at)}


def published(db):
    """已发布的全部规则版本，旧版本始终可查，按（生效时刻， 签发序号）排序。"""
    items = db.scalars(select(RuleVersion)).all()
    return sorted((as_dict(item) for item in items), key=sort_key)


def snapshot(db):
    """开跑时冻结的规则快照；尚无已发布版本时拒绝开跑。"""
    versions = published(db)
    if not versions:
        raise ValueError('尚无已发布的分流规则版本，请先在分流规则页发布后再验收')
    return [{'version': item['version'], 'effective_at': item['effective_at'],
             'issued_seq': item['issued_seq'], 'params': item['params']} for item in versions]


def publish(db, actor, body, effective_at):
    """单事务发布新版本；中断或校验失败时整体回滚，旧版本保持可查。"""
    item = RuleVersion(version=body.version, effective_at=effective_at, issued_seq=body.issued_seq,
                       params=normalize_params(body.params), author=actor.username)
    db.add(item)
    try:
        db.flush()
        record(db, actor.username, 'rule.published', item.id,
               version=item.version, effective_at=iso(item.effective_at), issued_seq=item.issued_seq)
        db.commit()
    except IntegrityError:
        db.rollback()
        clash = db.scalar(select(RuleVersion).where(RuleVersion.version == body.version))
        if clash:
            raise ValueError(f'规则版本号「{body.version}」已存在，请更换版本号') from None
        raise ValueError('同一生效时刻与签发序号的规则版本重叠，请调整签发序号') from None
    return item


def ensure_coverable(rows, versions):
    """导入前校验：版本重叠或任一来信缺生效规则时整批拒绝。"""
    overlap = find_overlap(versions)
    if overlap:
        stamp, seq = overlap
        raise ValueError(f'规则版本在 {stamp.isoformat()} 以签发序号 {seq} 重叠，批次整批拒绝，请先修订规则')
    if not versions:
        raise ValueError('尚无已发布的分流规则版本，批次整批拒绝，请先发布规则')
    for row in rows:
        if resolve(versions, row['arrived_at']) is None:
            raise ValueError(
                f"来信「{row['ticket_id']}」到件时刻 {row['arrived_at']} 没有已生效的分流规则，批次整批拒绝")
