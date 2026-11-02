import socket
import requests
import pytest
from urllib3.exceptions import MaxRetryError,NameResolutionError,ReadTimeoutError
from app.source_errors import classify,SourceNetworkError


@pytest.mark.parametrize('error,code',[
    (requests.ConnectTimeout('secret'),'connect_timeout'),
    (requests.ReadTimeout('secret'),'read_timeout'),
    (requests.exceptions.SSLError('secret'),'tls'),
    (requests.exceptions.ProxyError('secret'),'proxy'),
    (requests.ConnectionError(NameResolutionError('secret',None,socket.gaierror())),'dns'),
    (requests.ConnectionError(ConnectionResetError('secret')),'connection_reset'),
    (requests.ConnectionError(ReadTimeoutError(None,'secret','secret')),'read_timeout'),
    (requests.exceptions.ChunkedEncodingError('secret'),'response_stream'),
    (requests.ConnectionError('secret'),'connection'),
])
def test_classification_never_leaks_exception(error,code):
    result=SourceNetworkError('Поставщик',error)
    assert result.code==code and classify(error)==code
    assert code in str(result) and 'secret' not in str(result)


def test_exception_cycles_are_bounded():
    error=requests.ConnectionError('https://host/?password=private')
    error.__cause__=error
    assert classify(error)=='connection'
    assert 'private' not in str(SourceNetworkError('Поставщик',error))
