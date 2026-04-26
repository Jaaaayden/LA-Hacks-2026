"""Must be imported before any module that touches MongoDB at import-time.

`backend.kitscout.db` instantiates `AsyncIOMotorClient(os.environ["MONGODB_URI"])`
at module load. If MONGODB_URI isn't in the process env, that import raises a
KeyError. Importing this module first ensures `.env` has been loaded.

Also points Python's SSL stack at certifi's CA bundle — macOS / python.org
Python doesn't ship a system trust store by default, so aiohttp (which
uagents uses for the Agentverse mailbox) fails with "unable to get local
issuer certificate" when connecting to agentverse.ai over HTTPS.
"""

import os

import certifi
from dotenv import load_dotenv

load_dotenv()

# Use certifi's CA bundle for any HTTPS verification (aiohttp, requests, etc).
# setdefault: respects an already-set env if the user has a custom bundle.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
