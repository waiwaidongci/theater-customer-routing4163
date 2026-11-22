import csv
import hashlib
import io
import json
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from src.domain.demo import demo_rows
from src.domain.spec import SPEC
from src.models.source import Dataset
from src.services.validation import display_moment


def checksum(rows):
    raw = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def save(db, name, filename, rows, actor):
    signature = checksum(rows)
    lookup = select(Dataset).where(Dataset.name == name, Dataset.checksum == signature)
    existing = db.scalar(lookup)
    if existing:
        return existing, False
    dataset = Dataset(name=name, filename=filename, checksum=signature, rows=rows,
                      row_count=len(rows), author=actor)
    try:
        with db.begin_nested():
            db.add(dataset)
            db.flush()
    except IntegrityError:
        existing = db.scalar(lookup.with_for_update())
        if existing:
            return existing, False
        raise
    return dataset, True


def template():
    fields = [field['key'] for field in SPEC['fields']]
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction='ignore')
    writer.writeheader()
    # The complete representative dataset also works as a reproducible import fixture.
    # \u5230\u4ef6\u65f6\u95f4\u4ee5\u5317\u4eac\u65f6\u95f4\u5199\u56de\u6a21\u677f\uff0c\u91cd\u65b0\u5bfc\u5165\u540e\u6307\u7eb9\u4e0e\u6f14\u793a\u6279\u6b21\u4e00\u81f4\u3002
    for row in demo_rows():
        writer.writerow({**row, 'arrived_at': display_moment(row['arrived_at'])})
    return '\ufeff' + buffer.getvalue()
