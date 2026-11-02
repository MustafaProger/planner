"""Safe, bounded network diagnostics: never format upstream exceptions or requests."""
import socket
import requests


LABELS={
    'connect_timeout':'истекло время установления соединения',
    'read_timeout':'истекло время ожидания ответа',
    'tls':'ошибка проверки TLS',
    'proxy':'ошибка соединения через прокси',
    'dns':'не удалось разрешить имя сервера',
    'connection_reset':'соединение сброшено',
    'connection':'соединение не установлено или прервано',
    'timeout':'истекло время ожидания',
    'response_stream':'ответ прерван при чтении',
    'network':'сетевая ошибка',
}


def classify(error):
    """Inspect exception *types*, not text (URLs may contain passwords)."""
    found=[];queue=[error];seen=set()
    while queue and len(seen)<24:
        item=queue.pop(0)
        if not isinstance(item,BaseException) or id(item) in seen:continue
        seen.add(id(item));found.append(item)
        queue.extend([item.__cause__,item.__context__,getattr(item,'reason',None)])
        queue.extend(v for v in item.args if isinstance(v,BaseException))
    names={type(item).__name__ for item in found}
    if any(isinstance(e,requests.exceptions.ProxyError) for e in found):return 'proxy'
    if any(isinstance(e,requests.exceptions.SSLError) for e in found) or names&{'SSLCertVerificationError','SSLError'}:return 'tls'
    if any(isinstance(e,requests.exceptions.ConnectTimeout) for e in found) or 'ConnectTimeoutError' in names:return 'connect_timeout'
    if any(isinstance(e,requests.exceptions.ReadTimeout) for e in found) or 'ReadTimeoutError' in names:return 'read_timeout'
    if any(isinstance(e,socket.gaierror) for e in found) or 'NameResolutionError' in names:return 'dns'
    if any(isinstance(e,(ConnectionResetError,ConnectionAbortedError,BrokenPipeError)) for e in found) or 'RemoteDisconnected' in names:return 'connection_reset'
    if any(isinstance(e,requests.exceptions.Timeout) for e in found):return 'timeout'
    if any(isinstance(e,requests.exceptions.ChunkedEncodingError) for e in found):return 'response_stream'
    if any(isinstance(e,requests.exceptions.ConnectionError) for e in found):return 'connection'
    return 'network'


class SourceNetworkError(ValueError):
    def __init__(self,provider,error):
        self.provider=provider
        self.code=classify(error)
        super().__init__(f'{provider}: {LABELS[self.code]} [{self.code}]. Предыдущая загрузка сохранена; повтор выполняется по расписанию.')
