
import os
import msal
from flask import session, request

# Carrega as configurações do ambiente
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
AUTHORITY = os.getenv("AUTHORITY")
REDIRECT_PATH = os.getenv("REDIRECT_PATH")
SCOPE = [os.getenv("SCOPE")]

def _build_msal_app(cache=None, authority=None):
    """Cria uma instância do ConfidentialClientApplication da MSAL."""
    return msal.ConfidentialClientApplication(
        CLIENT_ID, authority=authority or AUTHORITY,
        client_credential=CLIENT_SECRET, token_cache=cache)

def _build_auth_url(authority=None, scopes=None, state=None):
    """Gera a URL de autorização para o usuário fazer login."""
    app = _build_msal_app(authority=authority)
    return app.get_authorization_request_url(
        scopes or SCOPE,
        state=state or session.get("state"),
        redirect_uri=request.url_root.rstrip('/') + REDIRECT_PATH)

def _get_token_from_code(authority=None, scopes=None):
    """Troca o código de autorização por um token de acesso."""
    cache = msal.SerializableTokenCache()
    if session.get("token_cache"):
        cache.deserialize(session["token_cache"])

    app = _build_msal_app(cache=cache, authority=authority)
    
    auth_code = request.args.get("code")
    if not auth_code:
        return None # Ou tratar o erro

    result = app.acquire_token_by_authorization_code(
        auth_code,
        scopes=scopes or SCOPE,
        redirect_uri=request.url_root.rstrip('/') + REDIRECT_PATH)

    if "access_token" in result:
        session["token_cache"] = cache.serialize()
        session["user"] = result.get("id_token_claims")

    return result
