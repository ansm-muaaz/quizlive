"""
QuizLive — Supabase client initialisation.

Provides two clients:
  • `supabase`         – uses the anon key (respects RLS, used for authenticated user operations)
  • `supabase_admin`   – uses the service-role key (bypasses RLS, used for server-side operations)

If Config.DEMO_MODE is True (or Supabase credentials are not provided),
this module automatically falls back to the local mock client (`mock_supabase_client`).
"""

import logging
from config import Config

logger = logging.getLogger(__name__)

IS_DEMO_MODE = Config.DEMO_MODE

if IS_DEMO_MODE:
    from mock_supabase import mock_supabase_client
    logger.info("[QuizLive] Running in LOCAL DEMO MODE (zero external dependencies).")
    supabase = mock_supabase_client
    supabase_admin = mock_supabase_client
else:
    try:
        from supabase import create_client, Client
        supabase: Client = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
        supabase_admin: Client = create_client(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY)
        logger.info("[QuizLive] Connected to Supabase Cloud platform.")
    except Exception as e:
        logger.warning(f"[QuizLive] Failed to connect to Supabase Cloud: {e}. Falling back to Local Demo Mode.")
        from mock_supabase import mock_supabase_client
        IS_DEMO_MODE = True
        supabase = mock_supabase_client
        supabase_admin = mock_supabase_client
