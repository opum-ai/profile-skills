import re

_KV = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|\S+)')
_LEVELS = {"debug": 10, "info": 20, "warn": 30, "error": 40}


def parse(line):
    """Parse `ts level msg key=value key="quoted value" ...` into a dict."""
    ts, level, rest = line.split(" ", 2)
    msg, _, kvs = rest.partition(" | ")
    fields = {}
    for k, v in _KV.findall(kvs):
        if v.startswith('"'):
            v = v[1:-1].replace('\\"', '"')
        fields[k] = v
    return {"ts": int(ts), "level": _LEVELS[level], "msg": msg, "fields": fields}


def parse_many(lines):
    return [parse(l) for l in lines if l.strip()]
