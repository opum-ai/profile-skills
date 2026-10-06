import pytest

from fastparse import parse, parse_many


def test_parse_basic():
    r = parse('1760000000 info user login | user=alice ip=10.0.0.1 agent="Mozilla 5.0"')
    assert r == {"ts": 1760000000, "level": 20, "msg": "user login",
                 "fields": {"user": "alice", "ip": "10.0.0.1", "agent": "Mozilla 5.0"}}


def test_escaped_quote():
    assert parse('1 warn x | q="say \\"hi\\""')["fields"]["q"] == 'say "hi"'


def test_unknown_level():
    with pytest.raises(KeyError):
        parse("1 trace x | a=1")


def test_parse_many_skips_blank():
    assert len(parse_many(["1 info a | x=1", "", "  ", "2 error b | y=2"])) == 2
