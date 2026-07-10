from slowapi import Limiter
from slowapi.util import get_remote_address

# Initialize Global Rate Limiter
# This is placed here to avoid circular imports between main.py and route files.
# get remote address will track it on IP address.
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])
