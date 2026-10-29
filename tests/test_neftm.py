import json
from pathlib import Path
import pytest
import requests
from app import neftm

XML=b'''<transactions><transaction><amount>100.50</amount><cardNumber>0000123</cardNumber><cardHolder>&lt;script&gt;</cardHolder><costClient>5500.25</costClient><currencyName>RUB</currencyName><dateRec>2026-08-31T23:59:59+03:00</dateRec><priceClient>54.729</priceClient><serviceName>Fuel</serviceName><typeNumber>11</typeNumber></transaction><transaction><amount>10</amount><costClient>550</costClient><dateRec>2026-08-31T23:59:59+03:00</dateRec><priceClient>55</priceClient><serviceName>Fuel</serviceName><typeNumber>24</typeNumber></transaction></transactions>'''


def test_parsing_preserves_decimals_returns_and_card_numbers():
    rows=neftm.parse_transactions(XML)
    assert rows[0]['cardNumber']=='0000123'
    assert rows[0]['costClient']=='5500.25'
    assert rows[0]['cardHolder']=='<script>'
    assert rows[1]['typeNumber']=='24'
    assert rows[1]['amount']=='10'
    duplicate=XML.replace(b'</transactions>',XML.split(b'<transactions>')[1])
    assert len(neftm.parse_transactions(duplicate))==4


@pytest.mark.parametrize('content',[b'<html>Login</html>',b'<!DOCTYPE transactions><transactions/>',b'<transactions><broken/></transactions>',b'<transactions><transaction/></transactions>',XML.replace(b'100.50',b'NaN')])
def test_bad_response_not_imported(content):
    with pytest.raises(ValueError):neftm.parse_transactions(content)


@pytest.mark.parametrize('a,b',[(None,None),('bad','2026-08-01'),('2026-09-01','2026-08-01'),('2026-01-01','2026-08-01')])
def test_bad_period(a,b):
    with pytest.raises(ValueError):neftm.period(a,b)


def fake_session(monkeypatch, status=200, content=XML, error=None):
    calls=[]
    class Response:
        status_code=status
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_content(self,*args):yield content
    class Session:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,**kwargs):
            calls.append((url,kwargs))
            if error:raise error
            return Response()
    monkeypatch.setattr(neftm.requests,'Session',Session)
    return calls


def test_sync_replaces_snapshot_without_duplicating(tmp_path,monkeypatch):
    (tmp_path/'neftm-api.key').write_text('test-only-key')
    calls=fake_session(monkeypatch)
    for _ in range(2):neftm.sync(tmp_path,'2026-08-01','2026-08-31')
    saved=neftm.snapshot(tmp_path)
    assert len(saved['rows'])==2
    assert 'test-only-key' not in json.dumps(saved)
    assert (tmp_path/'neftm-transactions.json').stat().st_mode & 0o777 == 0o600
    assert calls[0][0]==neftm.URL
    assert calls[0][1]['allow_redirects'] is False
    assert calls[0][1]['json']['format']=='XML'


@pytest.mark.parametrize('status,content,error',[(401,XML,None),(302,XML,None),(500,XML,None),(200,b'<html/>',None),(200,XML,requests.Timeout('private details'))])
def test_failure_preserves_previous_snapshot(tmp_path,monkeypatch,status,content,error):
    (tmp_path/'neftm-api.key').write_text('test-only-key')
    p=tmp_path/'neftm-transactions.json';p.write_text('{"previous":true}')
    fake_session(monkeypatch,status,content,error)
    with pytest.raises(ValueError) as e:neftm.sync(tmp_path,'2026-08-01','2026-08-31')
    assert 'private details' not in str(e.value)
    assert p.read_text()=='{"previous":true}'


def test_empty_success_is_valid():
    assert neftm.parse_transactions(b'<transactions/>')==[]
