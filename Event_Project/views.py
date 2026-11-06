import logging
from django.conf import settings
from django.db import connection
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions

logger = logging.getLogger(__name__)


class HealthCheckView(APIView):
    """
    Health check endpoint monitoring PostgreSQL and Redis connectivity.
    Returns HTTP 200 if all services are operational, or HTTP 503 if any service fails.
    """
    permission_classes = [permissions.AllowAny]
    swagger_schema = None

    def get(self, request, *args, **kwargs):
        services = {}
        all_healthy = True

        # 1. Check PostgreSQL Database connection
        try:
            connection.ensure_connection()
            services['database'] = 'healthy'
        except Exception as e:
            logger.error(f"Health check failed for database: {e}")
            services['database'] = f'unhealthy: {str(e)}'
            all_healthy = False

        # 2. Check Redis / Celery Broker connection
        try:
            import redis
            broker_url = getattr(settings, 'CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')
            r = redis.from_url(broker_url, socket_timeout=2)
            if r.ping():
                services['redis'] = 'healthy'
            else:
                services['redis'] = 'unresponsive'
                all_healthy = False
        except Exception as e:
            logger.error(f"Health check failed for Redis: {e}")
            services['redis'] = f'unhealthy: {str(e)}'
            all_healthy = False

        payload = {
            'status': 'healthy' if all_healthy else 'degraded',
            'timestamp': timezone.now().isoformat(),
            'services': services
        }

        http_status = status.HTTP_200_OK if all_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response(payload, status=http_status)

