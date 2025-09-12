import requests
from django.http import HttpResponse, Http404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator
from django.views import View
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone

import structlog

from posthog.models import Team
from .models import StreamlitApp

logger = structlog.get_logger(__name__)


@method_decorator([csrf_exempt, login_required], name='dispatch')
class StreamlitProxyView(View):
    """
    Proxy view for accessing Streamlit apps.
    Routes /streamlit/{app_id}/ to the actual container.
    """
    
    def get(self, request, app_id):
        return self._proxy_request(request, app_id, 'GET')
    
    def post(self, request, app_id):
        return self._proxy_request(request, app_id, 'POST')
    
    def put(self, request, app_id):
        return self._proxy_request(request, app_id, 'PUT')
    
    def delete(self, request, app_id):
        return self._proxy_request(request, app_id, 'DELETE')
    
    def _proxy_request(self, request, app_id, method):
        try:
            # Get the Streamlit app
            app = get_object_or_404(StreamlitApp, id=app_id)
            
            # Check if user has access to the team
            if not request.user.team or request.user.team.id != app.team.id:
                return HttpResponse("Access denied", status=403)
            
            # Check if app is running
            if app.container_status != StreamlitApp.ContainerStatus.RUNNING:
                return HttpResponse("App is not running", status=503)
            
            if not app.internal_url:
                return HttpResponse("App URL not configured", status=503)
            
            # Update last accessed time
            app.last_accessed = timezone.now()
            app.save(update_fields=['last_accessed'])
            
            # Build the target URL
            target_url = app.internal_url + request.get_full_path().replace(f'/streamlit/{app_id}', '')
            if not target_url.endswith('/') and not target_url.split('/')[-1].count('.'):
                target_url += '/'
            
            # Prepare headers for the proxy request
            headers = {
                'User-Agent': request.META.get('HTTP_USER_AGENT', ''),
                'Accept': request.META.get('HTTP_ACCEPT', '*/*'),
                'Accept-Language': request.META.get('HTTP_ACCEPT_LANGUAGE', ''),
                'Accept-Encoding': request.META.get('HTTP_ACCEPT_ENCODING', ''),
            }
            
            # Handle WebSocket upgrade headers for Streamlit
            if request.META.get('HTTP_UPGRADE') == 'websocket':
                headers['Upgrade'] = 'websocket'
                headers['Connection'] = 'Upgrade'
                headers['Sec-WebSocket-Key'] = request.META.get('HTTP_SEC_WEBSOCKET_KEY', '')
                headers['Sec-WebSocket-Version'] = request.META.get('HTTP_SEC_WEBSOCKET_VERSION', '')
            
            # Make the request to the container
            if method == 'GET':
                response = requests.get(target_url, headers=headers, stream=True, timeout=30)
            elif method == 'POST':
                response = requests.post(
                    target_url, 
                    data=request.body, 
                    headers=headers, 
                    stream=True, 
                    timeout=30
                )
            elif method == 'PUT':
                response = requests.put(
                    target_url, 
                    data=request.body, 
                    headers=headers, 
                    stream=True, 
                    timeout=30
                )
            elif method == 'DELETE':
                response = requests.delete(target_url, headers=headers, stream=True, timeout=30)
            else:
                return HttpResponse("Method not allowed", status=405)
            
            # Create response with appropriate headers
            django_response = HttpResponse(
                response.content,
                status=response.status_code,
                content_type=response.headers.get('content-type', 'text/html')
            )
            
            # Copy relevant headers
            for header, value in response.headers.items():
                if header.lower() in ['content-type', 'content-length', 'cache-control']:
                    django_response[header] = value
            
            return django_response
            
        except requests.exceptions.RequestException as e:
            logger.error("Failed to proxy request to Streamlit app", 
                        app_id=app_id, error=str(e))
            return HttpResponse("Streamlit app unavailable", status=503)
        except Exception as e:
            logger.error("Unexpected error in Streamlit proxy", 
                        app_id=app_id, error=str(e))
            return HttpResponse("Internal server error", status=500)
