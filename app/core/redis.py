import logging 

import redis 
from redis.exceptions import RedisError 

from app.core.config import settings 

logger = logging.getLogger(__name__)

# De endpoint /health khong bi treo qua lau khi Redis gap su co 
REDIS_TIMEOUT_SECONDS = 2 

redis_client = redis.Redis.from_url (
    settings.REDIS_URL,
    decode_responses = True, 
    socket_connect_timeout = REDIS_TIMEOUT_SECONDS,
    socket_timeout = REDIS_TIMEOUT_SECONDS,
)

def get_redis() -> redis.Redis: 
    # Dependency tra ve redis client dung chung (quan ly qua pool noi bo)
    return redis_client

def check_redis_connection() -> bool:

    try: 
        # gui lenh ping de xac minh connect voi redis 
        return bool(redis_client.ping())
    except RedisError:
        logger.exception("Khong the ket noi toi Redis khi kiem tra health.")
        return False