import logging
import sys
import types
import warnings
from inspect import isawaitable
from traceback import format_exc

try:
    import sanic
    from sanic import Sanic
    from sanic.exceptions import NotFound
    from sanic.response import HTTPResponse, StreamingHTTPResponse
except ImportError:
    print("Sanic is not installed. Please install it before using this library.")
try:
    import django
    from django import http
    from django.core.exceptions import (
        PermissionDenied, SuspiciousOperation,
    )
    from django.utils.version import get_complete_version
    from django.http.multipartparser import MultiPartParserError
    from django.conf import settings
    from django.core import signals, urlresolvers
    from django.core.handlers.base import BaseHandler
    from django.views import debug
    django_version = get_complete_version(None)
    if django_version >= (1, 10, 0):
        from django.urls import get_resolver, get_urlconf, set_urlconf
        from django.core.exceptions import ImproperlyConfigured, MiddlewareNotUsed
        from django.utils.module_loading import import_string
        from django.utils.deprecation import RemovedInDjango20Warning
        from django.core.handlers.exception import (
            convert_exception_to_response, get_exception_response,
            handle_uncaught_exception,
        )
    else:
        from django.utils.encoding import force_text
except ImportError:
    print("Django is not installed. Please install it before using this library.")
    BaseHandler = object
    django_version = (0, 0, 0)

from django_sanic_adaptor import SanicDjangoAdaptorRequest, SanicDjangoAdaptorResponse, SanicDjangoAdaptorStreamingResponse

logger = logging.getLogger('django.request')


class SanicHandler(BaseHandler):
    #initLock = Lock()
    request_class = SanicDjangoAdaptorRequest

    def __new__(cls, *args, **kwargs):
        cls = super(SanicHandler, cls).__new__(cls)
        if django_version >= (1, 10, 0):
            cls.async_get_response = cls.async_get_response_dj_1_10
            cls._get_response = cls._get_response_inner_dj_1_10
            cls._legacy_get_response = cls.async_legacy_get_response_dj_1_10
            cls.async_load_middleware = cls.async_load_middleware_dj_1_10
        else:
            cls.async_get_response = cls.async_get_response_dj_1_8
        return cls

    def __init__(self, app):
        super(SanicHandler, self).__init__()
        self.app = app

    async def async_get_response(self, request):
        return NotImplementedError("This should not occur.")

    async def async_load_middleware(self):
        return self.load_middleware()

    # This function is protected under the Django BSD 3-Clause licence
    # This function is reproduced under the terms of the Django Licence
    # See DJANGO_LICENCE in this source code repository
    async def async_load_middleware_dj_1_10(self):
        """
        Populate middleware lists from settings.MIDDLEWARE (or the deprecated
        MIDDLEWARE_CLASSES).
        Must be called after the environment is fixed (see __call__ in subclasses).
        """
        self._request_middleware = []
        self._view_middleware = []
        self._template_response_middleware = []
        self._response_middleware = []
        self._exception_middleware = []

        if settings.MIDDLEWARE is None:
            warnings.warn(
                "Old-style middleware using settings.MIDDLEWARE_CLASSES is "
                "deprecated. Update your middleware and use settings.MIDDLEWARE "
                "instead.", RemovedInDjango20Warning
            )
            handler = convert_exception_to_response(self._legacy_get_response)
            for middleware_path in settings.MIDDLEWARE_CLASSES:
                mw_class = import_string(middleware_path)
                try:
                    mw_instance = mw_class()
                except MiddlewareNotUsed as exc:
                    if settings.DEBUG:
                        if isinstance(exc, str):
                            logger.debug('MiddlewareNotUsed(%r): %s', middleware_path, exc)
                        else:
                            logger.debug('MiddlewareNotUsed: %r', middleware_path)
                    continue

                if hasattr(mw_instance, 'process_request'):
                    self._request_middleware.append(mw_instance.process_request)
                if hasattr(mw_instance, 'process_view'):
                    self._view_middleware.append(mw_instance.process_view)
                if hasattr(mw_instance, 'process_template_response'):
                    self._template_response_middleware.insert(0, mw_instance.process_template_response)
                if hasattr(mw_instance, 'process_response'):
                    self._response_middleware.insert(0, mw_instance.process_response)
                if hasattr(mw_instance, 'process_exception'):
                    self._exception_middleware.insert(0, mw_instance.process_exception)
        else:
            handler = convert_exception_to_response(self._get_response)
            for middleware_path in reversed(settings.MIDDLEWARE):
                middleware = import_string(middleware_path)
                try:
                    mw_instance = middleware(handler)
                except MiddlewareNotUsed as exc:
                    if settings.DEBUG:
                        if isinstance(exc, str):
                            logger.debug('MiddlewareNotUsed(%r): %s', middleware_path, exc)
                        else:
                            logger.debug('MiddlewareNotUsed: %r', middleware_path)
                    continue

                if mw_instance is None:
                    raise ImproperlyConfigured(
                        'Middleware factory %s returned None.' % middleware_path
                    )

                if hasattr(mw_instance, 'process_view'):
                    self._view_middleware.insert(0, mw_instance.process_view)
                if hasattr(mw_instance, 'process_template_response'):
                    self._template_response_middleware.append(mw_instance.process_template_response)
                if hasattr(mw_instance, 'process_exception'):
                    self._exception_middleware.append(mw_instance.process_exception)

                handler = convert_exception_to_response(mw_instance)

                # We only assign to this when initialization is complete as it is used
                # as a flag for initialization being complete.

        self._middleware_chain = handler

    # This function is protected under the Django BSD 3-Clause licence
    # This function is reproduced under the terms of the Django Licence
    # See DJANGO_LICENCE in this source code repository
    async def async_legacy_get_response_dj_1_10(self, request):
        """
        Apply process_request() middleware and call the main _get_response(),
        if needed. Used only for legacy MIDDLEWARE_CLASSES.
        """
        response = None
        # Apply request middleware
        for middleware_method in self._request_middleware:
            response = middleware_method(request)
            if isawaitable(response):
                response = await response
            if response:
                break

        if response is None:
            response = self._get_response(request)

        return response

    # This function is protected under the Django BSD 3-Clause licence
    # This function is reproduced under the terms of the Django Licence
    # See DJANGO_LICENCE in this source code repository
    async def async_get_response_dj_1_10(self, request):
        """This is the get_response function copied directly from Django 1.10.0"""
        """With the addition of async compatibility"""
        """Return an HttpResponse object for the given HttpRequest."""
        # Setup default url resolver for this thread
        set_urlconf(settings.ROOT_URLCONF)

        response = self._middleware_chain(request)
        if isawaitable(response):
            response = await response
        try:
            # Apply response middleware, regardless of the response
            for middleware_method in self._response_middleware:
                response = middleware_method(request, response)
                if isawaitable(response):
                    response = await response
                # Complain if the response middleware returned None (a common error).
                if response is None:
                    raise ValueError(
                        "%s.process_response didn't return an "
                        "HttpResponse object. It returned None instead."
                        % (middleware_method.__self__.__class__.__name__))
        except Exception:  # Any exception should be gathered and handled
            signals.got_request_exception.send(sender=self.__class__, request=request)
            response = self.handle_uncaught_exception(request, get_resolver(get_urlconf()), sys.exc_info())

        response._closable_objects.append(request)

        # If the exception handler returns a TemplateResponse that has not
        # been rendered, force it to be rendered.
        if not getattr(response, 'is_rendered', True) and callable(getattr(response, 'render', None)):
            response = response.render()
            if isawaitable(response):
                response = await response

        if response.status_code == 404:
            logger.warning(
                'Not Found: %s', request.path,
                extra={'status_code': 404, 'request': request},
            )

        return response

    async def _get_response_inner_dj_1_10(self, request):
        response = None

        if hasattr(request, 'urlconf'):
            urlconf = request.urlconf
            set_urlconf(urlconf)
            resolver = get_resolver(urlconf)
        else:
            resolver = get_resolver()

        resolver_match = resolver.resolve(request.path_info)
        callback, callback_args, callback_kwargs = resolver_match
        request.resolver_match = resolver_match

        # Apply view middleware
        for middleware_method in self._view_middleware:
            response = middleware_method(request, callback, callback_args, callback_kwargs)
            if isawaitable(response):
                response = await response
            if response:
                return response

        wrapped_callback = self.make_view_atomic(callback)
        try:
            response = wrapped_callback(request, *callback_args, **callback_kwargs)
            if isawaitable(response):
                response = await response
        except Exception as e:
            response = self.process_exception_by_middleware(e, request)
            if isawaitable(response):
                response = await response

        # Complain if the view returned None (a common error).
        if response is None:
            if isinstance(callback, types.FunctionType):  # FBV
                view_name = callback.__name__
            else:  # CBV
                view_name = callback.__class__.__name__ + '.__call__'

            raise ValueError(
                "The view %s.%s didn't return an HttpResponse object. It "
                "returned None instead." % (callback.__module__, view_name)
            )

        # If the response supports deferred rendering, apply template
        # response middleware and then render the response
        elif hasattr(response, 'render') and callable(response.render):
            for middleware_method in self._template_response_middleware:
                response = middleware_method(request, response)
                if isawaitable(response):
                    response = await response
                # Complain if the template response middleware returned None (a common error).
                if response is None:
                    raise ValueError(
                        "%s.process_template_response didn't return an "
                        "HttpResponse object. It returned None instead."
                        % (middleware_method.__self__.__class__.__name__)
                    )

            try:
                response = response.render()
                if isawaitable(response):
                    response = await response
            except Exception as e:
                response = self.process_exception_by_middleware(e, request)

        return response

    # This function is protected under the Django BSD 3-Clause licence
    # This function is reproduced under the terms of the Django Licence
    # See DJANGO_LICENCE in this source code repository
    async def async_get_response_dj_1_8(self, request):
        """
        This is the get_response function copied directly from Django 1.8.2
        With modifications to enable support for async responses.
        :param request:
        :return:
        """
        "Returns an HttpResponse object for the given HttpRequest"

        # Setup default url resolver for this thread, this code is outside
        # the try/except so we don't get a spurious "unbound local
        # variable" exception in the event an exception is raised before
        # resolver is set
        urlconf = settings.ROOT_URLCONF
        urlresolvers.set_urlconf(urlconf)
        resolver = urlresolvers.RegexURLResolver(r'^/', urlconf)
        try:
            response = None
            # Apply request middleware
            for middleware_method in self._request_middleware:
                response = middleware_method(request)
                if isawaitable(response):
                    response = await response
                if response:
                    break

            if response is None:
                if hasattr(request, 'urlconf'):
                    # Reset url resolver with a custom urlconf.
                    urlconf = request.urlconf
                    urlresolvers.set_urlconf(urlconf)
                    resolver = urlresolvers.RegexURLResolver(r'^/', urlconf)

                resolver_match = resolver.resolve(request.path_info)
                callback, callback_args, callback_kwargs = resolver_match
                request.resolver_match = resolver_match

                # Apply view middleware
                for middleware_method in self._view_middleware:
                    response = middleware_method(request, callback, callback_args, callback_kwargs)
                    if isawaitable(response):
                        response = await response
                    if response:
                        break

            if response is None:
                wrapped_callback = self.make_view_atomic(callback)
                try:
                    response = wrapped_callback(request, *callback_args, **callback_kwargs)
                    if isawaitable(response):
                        response = await response
                except Exception as e:
                    # If the view raised an exception, run it through exception
                    # middleware, and if the exception middleware returns a
                    # response, use that. Otherwise, reraise the exception.
                    for middleware_method in self._exception_middleware:
                        response = middleware_method(request, e)
                        if isawaitable(response):
                            response = await response
                        if response:
                            break
                    if response is None:
                        raise

            # Complain if the view returned None (a common error).
            if response is None:
                if isinstance(callback, types.FunctionType):    # FBV
                    view_name = callback.__name__
                else:                                           # CBV
                    view_name = callback.__class__.__name__ + '.__call__'
                raise ValueError("The view %s.%s didn't return an HttpResponse object. It returned None instead."
                                 % (callback.__module__, view_name))

            # If the response supports deferred rendering, apply template
            # response middleware and then render the response
            if hasattr(response, 'render') and callable(response.render):
                for middleware_method in self._template_response_middleware:
                    response = middleware_method(request, response)
                    if isawaitable(response):
                        response = await response
                    # Complain if the template response middleware returned None (a common error).
                    if response is None:
                        raise ValueError(
                            "%s.process_template_response didn't return an "
                            "HttpResponse object. It returned None instead."
                            % (middleware_method.__self__.__class__.__name__))
                response = response.render()
                if isawaitable(response):
                    response = await response

        except http.Http404 as e:
            logger.warning('Not Found: %s', request.path,
                        extra={
                            'status_code': 404,
                            'request': request
                        })
            if settings.DEBUG:
                response = debug.technical_404_response(request, e)
            else:
                response = self.get_exception_response(request, resolver, 404)

        except PermissionDenied:
            logger.warning(
                'Forbidden (Permission denied): %s', request.path,
                extra={
                    'status_code': 403,
                    'request': request
                })
            response = self.get_exception_response(request, resolver, 403)

        except MultiPartParserError:
            logger.warning(
                'Bad request (Unable to parse request body): %s', request.path,
                extra={
                    'status_code': 400,
                    'request': request
                })
            response = self.get_exception_response(request, resolver, 400)

        except SuspiciousOperation as e:
            # The request logger receives events for any problematic request
            # The security logger receives events for all SuspiciousOperations
            security_logger = logging.getLogger('django.security.%s' %
                            e.__class__.__name__)
            security_logger.error(
                force_text(e),
                extra={
                    'status_code': 400,
                    'request': request
                })
            if settings.DEBUG:
                return debug.technical_500_response(request, *sys.exc_info(), status_code=400)

            response = self.get_exception_response(request, resolver, 400)

        except SystemExit:
            # Allow sys.exit() to actually exit. See tickets #1023 and #4701
            raise

        except Exception:  # Handle everything else.
            # Get the exception info now, in case another exception is thrown later.
            signals.got_request_exception.send(sender=self.__class__, request=request)
            response = self.handle_uncaught_exception(request, resolver, sys.exc_info())

        try:
            # Apply response middleware, regardless of the response
            for middleware_method in self._response_middleware:
                response = middleware_method(request, response)
                if isawaitable(response):
                    response = await response
                # Complain if the response middleware returned None (a common error).
                if response is None:
                    raise ValueError(
                        "%s.process_response didn't return an "
                        "HttpResponse object. It returned None instead."
                        % (middleware_method.__self__.__class__.__name__))
            response = self.apply_response_fixes(request, response)
        except Exception:  # Any exception should be gathered and handled
            signals.got_request_exception.send(sender=self.__class__, request=request)
            response = self.handle_uncaught_exception(request, resolver, sys.exc_info())

        response._closable_objects.append(request)

        return response

    # This function is protected under the Sanic MIT licence
    # This function is reproduced under the terms of the Sanic Licence
    # See SANIC_LICENCE in this source code repository
    async def __call__(self, request, write_callback, stream_callback):
        """ This is essentially directly copied from Sanic handle_request() function
        Take a request from the HTTP Server and return a response object
        to be sent back The HTTP Server only expects a response object, so
        exception handling must be done here

        :param request: HTTP Request object
        :param write_callback: Synchronous response function to be
            called with the response as the only argument
        :param stream_callback: Coroutine that handles streaming a
            StreamingHTTPResponse if produced by the handler.

        :return: Nothing
        """
        try:
            # -------------------------------------------- #
            # Request Middleware
            # -------------------------------------------- #

            request.app = self.app
            if self._request_middleware is None:
                try:
                    await self.async_load_middleware()
                except Exception:
                    # Unload whatever middleware we got
                    self._request_middleware = None
                    raise
            signals.request_started.send(sender=self.__class__)

            # Run Sanic Middleware
            response = await self.app._run_request_middleware(request)
            # No middleware results
            if not response:
                # -------------------------------------------- #
                # Execute Handler
                # -------------------------------------------- #
                # Fetch possible handler from Sanic router first
                try:
                    sanic_handler, args, kwargs, uri = self.app.router.get(request)
                    if sanic_handler is not None:
                        request.uri_template = uri
                        # Run response handler
                        response = sanic_handler(request, *args, **kwargs)
                except NotFound:
                    pass
                if not response:
                    # Now do the Django magic.
                    try:
                        django_request = self.request_class(request)
                    except UnicodeDecodeError:
                        logger.warning('Bad Request (UnicodeDecodeError)',
                                       exc_info=sys.exc_info(),
                                       extra={'status_code': 400,})
                        response = HTTPResponse(status=401) #bad request
                    else:
                        django_response = await self.async_get_response(django_request)
                        if django_response.streaming:
                            response = SanicDjangoAdaptorStreamingResponse(django_response)
                        else:
                            response = SanicDjangoAdaptorResponse(django_response)
                    # Fetch handler from router
                if isawaitable(response):
                    response = await response
        except Exception as e:
            # -------------------------------------------- #
            # Response Generation Failed
            # -------------------------------------------- #

            try:
                response = self.app.error_handler.response(request, e)
                if isawaitable(response):
                    response = await response
            except Exception as e:
                if self.app.debug:
                    response = HTTPResponse(
                        "Error while handling error: {}\nStack: {}".format(
                            e, format_exc()))
                else:
                    response = HTTPResponse(
                        "An error occurred while handling an error")
        finally:
            # -------------------------------------------- #
            # Response Middleware
            # -------------------------------------------- #
            try:
                response = await self.app._run_response_middleware(request, response)
            except Exception:
                logger.exception(
                    'Exception occured in one of response middleware handlers'
                )

        # pass the response to the correct callback
        if isinstance(response, StreamingHTTPResponse):
            await stream_callback(response)
        else:
            write_callback(response)


def get_sanic_application():
    """
    Sets up django and returns a Sanic application
    """
    if sys.version_info < (3, 5):
        raise RuntimeError("The SanicDjango Adaptor may only be used with python 3.5 and above.")
    django.setup()
    from django.conf import settings
    DEBUG = getattr(settings, 'DEBUG', False)
    INSTALLED_APPS = getattr(settings, 'INSTALLED_APPS', [])
    do_static = DEBUG and 'django.contrib.staticfiles' in INSTALLED_APPS
    app = Sanic(__name__)
    if do_static:
        static_url = getattr(settings, 'STATIC_URL', "/static/")
        static_root = getattr(settings, 'STATIC_ROOT', "./static")
        app.static(static_url, static_root)
    app.handle_request = SanicHandler(app)  # patch the app to use the django adaptor handler
    return app


