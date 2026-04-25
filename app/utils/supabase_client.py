"""Supabase client utility — lightweight REST wrapper (no SDK dependency)."""
import os
import requests
from datetime import datetime, timezone


class SupabaseClient:
    """Minimal Supabase client using REST API (PostgREST)."""

    def __init__(self):
        self.url = os.getenv('SUPABASE_URL', '').rstrip('/')
        self.key = os.getenv('SUPABASE_KEY', '')  # anon or service_role key
        self._ready = bool(self.url and self.key)
        if self._ready:
            print(f"[Supabase] Connected to {self.url}")
        else:
            print("[Supabase] WARNING: SUPABASE_URL or SUPABASE_KEY not set")

    def is_ready(self):
        return self._ready

    def _headers(self):
        return {
            'apikey': self.key,
            'Authorization': f'Bearer {self.key}',
            'Content-Type': 'application/json',
            'Prefer': 'return=representation'
        }

    # ── CRUD Operations ───────────────────────────────

    def insert(self, table: str, data: dict) -> dict | None:
        """Insert a row into a table. Returns the inserted row."""
        if not self._ready:
            return None
        try:
            resp = requests.post(
                f"{self.url}/rest/v1/{table}",
                json=data,
                headers=self._headers(),
                timeout=10
            )
            if resp.status_code in (200, 201):
                rows = resp.json()
                return rows[0] if rows else data
            else:
                print(f"[Supabase] Insert error {resp.status_code}: {resp.text[:200]}")
                return None
        except Exception as e:
            print(f"[Supabase] Insert exception: {e}")
            return None

    def select(self, table: str, filters: dict = None, order: str = None,
               limit: int = None, columns: str = '*') -> list:
        """Select rows from a table with optional filters."""
        if not self._ready:
            return []
        try:
            params = {'select': columns}
            url = f"{self.url}/rest/v1/{table}"

            # Build query string filters (PostgREST format)
            query_parts = []
            if filters:
                for key, value in filters.items():
                    query_parts.append(f"{key}=eq.{value}")

            if order:
                query_parts.append(f"order={order}")
            if limit:
                query_parts.append(f"limit={limit}")

            query_string = '&'.join(query_parts)
            if query_string:
                url += f"?{columns and f'select={columns}&' or ''}{query_string}"
            else:
                url += f"?select={columns}"

            resp = requests.get(url, headers=self._headers(), timeout=10)
            if resp.status_code == 200:
                return resp.json()
            else:
                print(f"[Supabase] Select error {resp.status_code}: {resp.text[:200]}")
                return []
        except Exception as e:
            print(f"[Supabase] Select exception: {e}")
            return []

    def update(self, table: str, filters: dict, data: dict) -> dict | None:
        """Update rows matching filters."""
        if not self._ready:
            return None
        try:
            url = f"{self.url}/rest/v1/{table}"
            query_parts = [f"{k}=eq.{v}" for k, v in filters.items()]
            url += '?' + '&'.join(query_parts)

            resp = requests.patch(
                url, json=data, headers=self._headers(), timeout=10
            )
            if resp.status_code == 200:
                rows = resp.json()
                return rows[0] if rows else data
            else:
                print(f"[Supabase] Update error {resp.status_code}: {resp.text[:200]}")
                return None
        except Exception as e:
            print(f"[Supabase] Update exception: {e}")
            return None

    def delete(self, table: str, filters: dict) -> bool:
        """Delete rows matching filters."""
        if not self._ready:
            return False
        try:
            url = f"{self.url}/rest/v1/{table}"
            query_parts = [f"{k}=eq.{v}" for k, v in filters.items()]
            url += '?' + '&'.join(query_parts)

            resp = requests.delete(url, headers=self._headers(), timeout=10)
            return resp.status_code in (200, 204)
        except Exception as e:
            print(f"[Supabase] Delete exception: {e}")
            return False

    def rpc(self, function_name: str, params: dict = None) -> any:
        """Call a Supabase RPC (stored procedure)."""
        if not self._ready:
            return None
        try:
            resp = requests.post(
                f"{self.url}/rest/v1/rpc/{function_name}",
                json=params or {},
                headers=self._headers(),
                timeout=10
            )
            if resp.status_code == 200:
                return resp.json()
            else:
                print(f"[Supabase] RPC error {resp.status_code}: {resp.text[:200]}")
                return None
        except Exception as e:
            print(f"[Supabase] RPC exception: {e}")
            return None

    # ── Convenience methods for chat ──────────────────

    def search_templates(self, keywords: list[str]) -> list:
        """Search response templates matching any of the given keywords."""
        if not self._ready:
            return []
        try:
            # Use PostgREST overlap operator for array matching
            kw_str = '{' + ','.join(keywords) + '}'
            url = (f"{self.url}/rest/v1/response_templates"
                   f"?select=*&is_active=eq.true&keywords=ov.{kw_str}"
                   f"&order=usage_count.desc&limit=5")
            resp = requests.get(url, headers=self._headers(), timeout=10)
            if resp.status_code == 200:
                return resp.json()
            return []
        except Exception as e:
            print(f"[Supabase] Template search error: {e}")
            return []


# Singleton instance
supabase = SupabaseClient()
