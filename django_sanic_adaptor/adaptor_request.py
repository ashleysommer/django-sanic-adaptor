import cgi
import warnings

try:
    import django
    from django.http import QueryDict as DjangoQueryDict, parse_cookie
    from django.http.request import HttpRequest as DjangoHttpRequest
    from django.http.response import HttpResponse as DjangoHttpResponse, \
        StreamingHttpResponse as DjangoStreamingResponse
    from django.utils import datastructures
    from django.utils.functional import cached_property
except ImportError:
    print("Django is not installed. Please install it before using this library.")
    DjangoHttpRequest = DjangoHttpResponse = DjangoStreamingResponse = object
    def cached_property(fn):
        """Dummy cached_property fn, to make setup.py work before installed."""
        return fn

try:
    import sanic
    from sanic.request import Request as SanicRequest
    from sanic.response import HTTPResponse as SanicHttpResponse, StreamingHTTPResponse as SanicStreamingResponse
except ImportError:
    print("Sanic is not installed. Please install it before using this library.")
    SanicRequest = SanicHttpResponse = SanicStreamingResponse = object

class WSGIRequest(DjangoHttpRequest):
    def __init__(self, environ):
        script_name = get_script_name(environ)
        path_info = get_path_info(environ)
        if not path_info:
            # Sometimes PATH_INFO exists, but is empty (e.g. accessing
            # the SCRIPT_NAME URL without a trailing slash). We really need to
            # operate as if they'd requested '/'. Not amazingly nice to force
            # the path like this, but should be harmless.
            path_info = '/'
        self.environ = environ
        self.path_info = path_info
        # be careful to only replace the first slash in the path because of
        # http://test/something and http://test//something being different as
        # stated in http://www.ietf.org/rfc/rfc2396.txt
        self.path = '%s/%s' % (script_name.rstrip('/'),
                               path_info.replace('/', '', 1))
        self.META = environ
        self.META['PATH_INFO'] = path_info
        self.META['SCRIPT_NAME'] = script_name
        self.method = environ['REQUEST_METHOD'].upper()
        _, content_params = cgi.parse_header(environ.get('CONTENT_TYPE', ''))
        if 'charset' in content_params:
            try:
                codecs.lookup(content_params['charset'])
            except LookupError:
                pass
            else:
                self.encoding = content_params['charset']
        self._post_parse_error = False
        try:
            content_length = int(environ.get('CONTENT_LENGTH'))
        except (ValueError, TypeError):
            content_length = 0
        self._stream = LimitedStream(self.environ['wsgi.input'], content_length)
        self._read_started = False
        self.resolver_match = None

    def _get_scheme(self):
        return self.environ.get('wsgi.url_scheme')

    def _get_request(self):
        warnings.warn('`request.REQUEST` is deprecated, use `request.GET` or '
                      '`request.POST` instead.', RemovedInDjango19Warning, 2)
        if not hasattr(self, '_request'):
            self._request = datastructures.MergeDict(self.POST, self.GET)
        return self._request

    @cached_property
    def GET(self):
        # The WSGI spec says 'QUERY_STRING' may be absent.
        raw_query_string = get_bytes_from_wsgi(self.environ, 'QUERY_STRING', '')
        return http.QueryDict(raw_query_string, encoding=self._encoding)

    def _get_post(self):
        if not hasattr(self, '_post'):
            self._load_post_and_files()
        return self._post

    def _set_post(self, post):
        self._post = post

    @cached_property
    def COOKIES(self):
        raw_cookie = get_str_from_wsgi(self.environ, 'HTTP_COOKIE', '')
        return http.parse_cookie(raw_cookie)

    def _get_files(self):
        if not hasattr(self, '_files'):
            self._load_post_and_files()
        return self._files

    POST = property(_get_post, _set_post)
    FILES = property(_get_files)
    REQUEST = property(_get_request)

class SanicDjangoAdaptorRequest(DjangoHttpRequest):

    def __init__(self, sanic_request):
        """
        
        :param SanicRequest sanic_request: 
        """
        #script_name = get_script_name(environ)
        #path_info = get_path_info(environ)
        script_name = "/"
        path_info = sanic_request.path
        if not path_info:
            # Sometimes PATH_INFO exists, but is empty (e.g. accessing
            # the SCRIPT_NAME URL without a trailing slash). We really need to
            # operate as if they'd requested '/'. Not amazingly nice to force
            # the path like this, but should be harmless.
            path_info = '/'
        self.sanic_request = sanic_request
        self.path_info = path_info
        # be careful to only replace the first slash in the path because of
        # http://test/something and http://test//something being different as
        # stated in http://www.ietf.org/rfc/rfc2396.txt
        self.path = '%s/%s' % (script_name.rstrip('/'),
                               path_info.replace('/', '', 1))
        self.META = {"HTTP_{:s}".format(str(k).upper()): v for (k, v) in sanic_request.headers.items()}
        self.META['REMOTE_ADDR'] = sanic_request.ip[0]
        self.META['PATH_INFO'] = path_info
        self.META['SCRIPT_NAME'] = script_name
        self.method = str(sanic_request.method).upper()
        # _, content_params = cgi.parse_header(environ.get('CONTENT_TYPE', ''))
        # if 'charset' in content_params:
        #     try:
        #         codecs.lookup(content_params['charset'])
        #     except LookupError:
        #         pass
        #     else:
        #         self.encoding = content_params['charset']
        self._post_parse_error = False
        try:
            content_length = int(sanic_request.headers['content-length'])
        except (KeyError, ValueError, TypeError):
            content_length = 0
        #self._stream = LimitedStream(self.environ['wsgi.input'], content_length)
        self._body = sanic_request.body
        self._read_started = False
        self.resolver_match = None

    def _get_scheme(self):
        return self.sanic_request.scheme

    def _get_request(self):
        warnings.warn('`request.REQUEST` is deprecated, use `request.GET` or '
                      '`request.POST` instead.', "Django Deprecation Warning", 2)
        if not hasattr(self, '_request'):
            self._request = {}
            self._request.update(self.POST)
            self._request.update(self.GET)
        return self._request

    @cached_property
    def GET(self):
        # The WSGI spec says 'QUERY_STRING' may be absent.
        #raw_query_string = get_bytes_from_wsgi(self.environ, 'QUERY_STRING', '')
        raw_query_string = self.sanic_request.query_string
        return DjangoQueryDict(raw_query_string, encoding=self._encoding)

    def _get_post(self):
        if not hasattr(self, '_post'):
            self._load_post_and_files()
        return self._post

    def _set_post(self, post):
        self._post = post

    @cached_property
    def COOKIES(self):
        #raw_cookie = get_str_from_wsgi(self.environ, 'HTTP_COOKIE', '')
        #return http.parse_cookie(raw_cookie)
        return self.sanic_request.cookies

    def _get_files(self):
        if not hasattr(self, '_files'):
            self._load_post_and_files()
        return self._files

    POST = property(_get_post, _set_post)
    FILES = property(_get_files)
    REQUEST = property(_get_request)


class SanicDjangoAdaptorResponse(SanicHttpResponse):

    def __init__(self, django_response):
        """
        :param DjangoHttpResponse django_response: 
        """
        body_bytes = django_response.content
        status = django_response.status_code
        headers = dict([h for h in django_response._headers.values()])
        # content-type is None here because Content-Type is set in the headers
        # in the djanog_response.
        super(SanicDjangoAdaptorResponse, self).__init__(body=None, status=status, headers=headers,
                                                         content_type=None, body_bytes=body_bytes)
        # These cookies are not already present in django_response headers. add them.
        _ = {self.cookies.__setitem__(morsel.key, morsel.value) for morsel in django_response.cookies.values()}


class SanicDjangoAdaptorStreamingResponse(SanicStreamingResponse):

    def __init__(self, django_response):
        """
        :param DjangoStreamingResponse django_response: 
        """
        status = django_response.status_code
        headers = dict([h for h in django_response._headers.values()])
        def _streaming_fn(response):
            nonlocal django_response
            _ = {response.write(c) for c in django_response.streaming_content}
        # content-type is None here because Content-Type is set in the headers
        # in the djanog_response.
        super(SanicDjangoAdaptorStreamingResponse, self).__init__(streaming_fn=_streaming_fn,
            status=status, headers=headers, content_type=None)
        # These cookies are not already present in django_response headers. add them.
        _ = {self.cookies.__setitem__(morsel.key, morsel.value) for morsel in django_response.cookies.values()}

