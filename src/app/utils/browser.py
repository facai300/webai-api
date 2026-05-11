# src/app/utils/browser.py
import logging
import browser_cookie3
import platform
import os
import sqlite3
import json
import base64
from pathlib import Path
from typing import Optional, Literal, Dict, Any
from app.config import CONFIG

# Windows-specific imports for cookie decryption
if platform.system().lower() == "windows":
    try:
        import win32crypt
        from Crypto.Cipher import AES
        HAS_CRYPTO = True
    except ImportError:
        HAS_CRYPTO = False
        logging.warning("Windows crypto libraries not available. Install with: pip install pywin32 pycryptodome")
else:
    HAS_CRYPTO = False

logger = logging.getLogger(__name__)

class CrossPlatformCookieExtractor:
    """Cross-platform cookie extractor with Windows compatibility fixes"""
    
    def __init__(self):
        self.system = platform.system().lower()
        self.is_windows = self.system == "windows"
        logger.info(f"Initialized cookie extractor for {self.system}")
    
    def _get_browser_profile_paths(self, browser_name: str) -> Dict[str, Any]:
        """Get browser profile paths for different operating systems"""
        paths = {}
        
        if self.is_windows:
            user_data = os.path.expanduser("~")
            if browser_name == "chrome":
                base_path = os.path.join(user_data, "AppData", "Local", "Google", "Chrome", "User Data")
                # Check multiple possible locations for Chrome cookies
                possible_paths = [
                    os.path.join(base_path, "Default", "Network", "Cookies"),  # New Chrome location
                    os.path.join(base_path, "Default", "Cookies"),  # Old Chrome location
                ]
                cookies_path = None
                for path in possible_paths:
                    if os.path.exists(path):
                        cookies_path = path
                        logger.info(f"Found Chrome cookies at: {path}")
                        break
                
                paths = {
                    "cookies_db": cookies_path,
                    "local_state": os.path.join(base_path, "Local State")
                }
                
            elif browser_name == "brave":
                base_path = os.path.join(user_data, "AppData", "Local", "BraveSoftware", "Brave-Browser", "User Data")
                # Check multiple possible locations for Brave cookies
                possible_paths = [
                    os.path.join(base_path, "Default", "Network", "Cookies"),  # New Brave location
                    os.path.join(base_path, "Default", "Cookies"),  # Old Brave location
                ]
                cookies_path = None
                for path in possible_paths:
                    if os.path.exists(path):
                        cookies_path = path
                        logger.info(f"Found Brave cookies at: {path}")
                        break
                
                paths = {
                    "cookies_db": cookies_path,
                    "local_state": os.path.join(base_path, "Local State")
                }
                
            elif browser_name == "edge":
                base_path = os.path.join(user_data, "AppData", "Local", "Microsoft", "Edge", "User Data")
                # Check multiple possible locations for Edge cookies
                possible_paths = [
                    os.path.join(base_path, "Default", "Network", "Cookies"),  # New Edge location
                    os.path.join(base_path, "Default", "Cookies"),  # Old Edge location
                ]
                cookies_path = None
                for path in possible_paths:
                    if os.path.exists(path):
                        cookies_path = path
                        logger.info(f"Found Edge cookies at: {path}")
                        break
                
                paths = {
                    "cookies_db": cookies_path,
                    "local_state": os.path.join(base_path, "Local State")
                }
                
            elif browser_name == "firefox":
                firefox_path = os.path.join(user_data, "AppData", "Roaming", "Mozilla", "Firefox", "Profiles")
                if os.path.exists(firefox_path):
                    profiles = [d for d in os.listdir(firefox_path) if os.path.isdir(os.path.join(firefox_path, d))]
                    if profiles:
                        profile_path = os.path.join(firefox_path, profiles[0])
                        paths = {"cookies_db": os.path.join(profile_path, "cookies.sqlite")}
        
        return paths
    
    def _try_browser_cookie3(self, browser_name: str) -> Optional[Any]:
        """Try to get cookies using browser_cookie3 library"""
        try:
            if browser_name == "firefox":
                return browser_cookie3.firefox()
            elif browser_name == "chrome":
                return browser_cookie3.chrome()
            elif browser_name == "brave":
                return browser_cookie3.brave()
            elif browser_name == "edge":
                return browser_cookie3.edge()
            elif browser_name == "safari":
                return browser_cookie3.safari()
            else:
                raise ValueError(f"Unsupported browser: {browser_name}")
        except Exception as e:
            logger.warning(f"browser_cookie3 failed for {browser_name}: {e}")
            return None
    
    def _decrypt_chrome_cookie_value(self, encrypted_value: bytes, local_state_path: str) -> Optional[str]:
        """Decrypt Chrome cookie value on Windows"""
        if not self.is_windows or not HAS_CRYPTO:
            logger.warning("Decryption not available: not Windows or crypto libraries missing")
            return None
            
        try:
            logger.info(f"Attempting decryption with Local State: {local_state_path}")
            logger.info(f"Encrypted value length: {len(encrypted_value)}")
            
            # Read the local state file to get the encryption key
            if not os.path.exists(local_state_path):
                logger.warning(f"Local State file not found: {local_state_path}")
                return None
                
            with open(local_state_path, 'r', encoding='utf-8') as f:
                local_state = json.load(f)
            
            # Get the encrypted key
            if 'os_crypt' not in local_state or 'encrypted_key' not in local_state['os_crypt']:
                logger.warning("os_crypt.encrypted_key not found in Local State")
                return None
                
            encrypted_key = base64.b64decode(local_state['os_crypt']['encrypted_key'])
            logger.info(f"Encrypted key length: {len(encrypted_key)}")
            
            # Remove the 'DPAPI' prefix (first 5 bytes)
            encrypted_key = encrypted_key[5:]
            
            # Decrypt the key using Windows DPAPI
            key = win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)[1]
            logger.info(f"Decrypted key length: {len(key)}")
            
            # The cookie value format: version (3 bytes) + nonce (12 bytes) + encrypted_data + tag (16 bytes)
            if len(encrypted_value) < 31:  # 3 + 12 + 1 + 16 = minimum length
                logger.warning(f"Encrypted value too short: {len(encrypted_value)} bytes")
                return None
                
            # Extract components
            version = encrypted_value[:3]
            logger.info(f"Cookie encryption version: {version}")
            
            if version != b'v10' and version != b'v11':
                # Try old DPAPI method for older Chrome versions
                logger.info("Trying DPAPI decryption for older Chrome")
                try:
                    decrypted = win32crypt.CryptUnprotectData(encrypted_value, None, None, None, 0)[1]
                    result = decrypted.decode('utf-8')
                    logger.info(f"DPAPI decryption successful, result length: {len(result)}")
                    return result
                except Exception as e:
                    logger.warning(f"DPAPI decryption failed: {e}")
                    return None
            
            nonce = encrypted_value[3:15]
            ciphertext = encrypted_value[15:-16]
            tag = encrypted_value[-16:]
            
            logger.info(f"AES-GCM components - nonce: {len(nonce)}, ciphertext: {len(ciphertext)}, tag: {len(tag)}")
            
            # Decrypt using AES-GCM
            cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
            decrypted = cipher.decrypt_and_verify(ciphertext, tag)
            
            result = decrypted.decode('utf-8')
            logger.info(f"AES-GCM decryption successful, result length: {len(result)}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to decrypt Chrome cookie: {e}", exc_info=True)
            return None
        """Direct Firefox cookie extraction from SQLite database"""
        try:
            if not os.path.exists(cookies_db_path):
                logger.warning(f"Firefox cookies database not found: {cookies_db_path}")
                return None
            
            # Copy the database to avoid lock issues
            import tempfile
            import shutil
            
            with tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False) as temp_file:
                temp_db_path = temp_file.name
                shutil.copy2(cookies_db_path, temp_db_path)
            
            try:
                conn = sqlite3.connect(temp_db_path)
                cursor = conn.cursor()
                
                # Firefox cookie table structure
                cursor.execute("""
                    SELECT name, value, host, path, expiry, isSecure, isHttpOnly 
                    FROM moz_cookies 
                    WHERE host LIKE '%google%' AND (name = '__Secure-1PSID' OR name = '__Secure-1PSIDTS')
                """)
                
                cookies = []
                for row in cursor.fetchall():
                    cookie_obj = type('Cookie', (), {
                        'name': row[0],
                        'value': row[1],
                        'domain': row[2],
                        'path': row[3],
                        'expires': row[4],
                        'secure': bool(row[5]),
                        'httponly': bool(row[6])
                    })()
                    cookies.append(cookie_obj)
                
                conn.close()
                return cookies
            finally:
                # Clean up temp file
                try:
                    os.unlink(temp_db_path)
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"Failed to extract Firefox cookies directly: {e}")
            return None
    
    def _get_chromium_cookies_direct(self, cookies_db_path: str, local_state_path: str = None) -> Optional[list]:
        """Direct Chromium-based browser cookie extraction with decryption support"""
        try:
            if not os.path.exists(cookies_db_path):
                logger.warning(f"Chromium cookies database not found: {cookies_db_path}")
                return None
            
            # Copy the database to avoid lock issues
            import tempfile
            import shutil
            
            with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as temp_file:
                temp_db_path = temp_file.name
                shutil.copy2(cookies_db_path, temp_db_path)
            
            try:
                conn = sqlite3.connect(temp_db_path)
                cursor = conn.cursor()
                
                # Chromium cookie table structure - get encrypted_value too
                cursor.execute("""
                    SELECT name, value, encrypted_value, host_key, path, expires_utc, is_secure, is_httponly 
                    FROM cookies 
                    WHERE host_key LIKE '%google%' AND (name = '__Secure-1PSID' OR name = '__Secure-1PSIDTS')
                """)
                
                logger.info(f"Found {cursor.rowcount} matching cookies in database")
                
                cookies = []
                for row in cursor.fetchall():
                    name, value, encrypted_value, host_key, path, expires_utc, is_secure, is_httponly = row
                    
                    logger.info(f"Processing cookie: {name}")
                    logger.info(f"  - Plain value length: {len(value) if value else 0}")
                    logger.info(f"  - Encrypted value length: {len(encrypted_value) if encrypted_value else 0}")
                    logger.info(f"  - Host: {host_key}")
                    
                    # Try to decrypt the cookie value if it's encrypted
                    final_value = value
                    if not value and encrypted_value and self.is_windows and local_state_path:
                        logger.info(f"  - Attempting to decrypt {name}")
                        decrypted_value = self._decrypt_chrome_cookie_value(encrypted_value, local_state_path)
                        if decrypted_value:
                            final_value = decrypted_value
                            logger.info(f"  - Successfully decrypted cookie: {name} (length: {len(final_value)})")
                        else:
                            logger.warning(f"  - Failed to decrypt cookie: {name}")
                    elif value:
                        logger.info(f"  - Using plain text value for {name}")
                    else:
                        logger.warning(f"  - No value found for {name} (neither plain nor encrypted)")
                    
                    cookie_obj = type('Cookie', (), {
                        'name': name,
                        'value': final_value or '',
                        'domain': host_key,
                        'path': path,
                        'expires': expires_utc,
                        'secure': bool(is_secure),
                        'httponly': bool(is_httponly)
                    })()
                    cookies.append(cookie_obj)
                
                conn.close()
                return cookies
            finally:
                # Clean up temp file
                try:
                    os.unlink(temp_db_path)
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"Failed to extract Chromium cookies directly: {e}")
            return None
    
    def get_cookies_with_fallback(self, browser_name: str) -> Optional[Any]:
        """Get cookies with multiple fallback methods"""
        logger.info(f"Attempting to get cookies from {browser_name} with fallback methods")
        
        # Method 1: Try browser_cookie3 first (works well on Linux)
        cookies = self._try_browser_cookie3(browser_name)
        if cookies:
            logger.info(f"Successfully retrieved cookies using browser_cookie3 for {browser_name}")
            return cookies
        
        # Method 2: Try direct database access (fallback for Windows)
        if self.is_windows:
            logger.info(f"Trying direct database access for {browser_name} on Windows")
            
            browser_paths = self._get_browser_profile_paths(browser_name)
            
            if browser_name == "firefox" and "cookies_db" in browser_paths:
                cookies = self._get_firefox_cookies_direct(browser_paths["cookies_db"])
                if cookies:
                    logger.info(f"Successfully retrieved Firefox cookies via direct access")
                    return cookies
            
            elif browser_name in ["chrome", "brave", "edge"] and "cookies_db" in browser_paths:
                cookies_db_path = browser_paths["cookies_db"]
                local_state_path = browser_paths.get("local_state")
                
                if cookies_db_path and os.path.exists(cookies_db_path):
                    cookies = self._get_chromium_cookies_direct(cookies_db_path, local_state_path)
                    if cookies:
                        logger.info(f"Successfully retrieved {browser_name} cookies via direct access")
                        return cookies
                else:
                    logger.warning(f"Cookies database not found for {browser_name} at expected locations")
        
        logger.warning(f"All cookie extraction methods failed for {browser_name}")
        return None


def get_cookie_from_browser(service: Literal["gemini"]) -> Optional[tuple]:
    """Enhanced cookie extraction with cross-platform support"""
    browser_name = CONFIG["Browser"].get("name", "firefox").lower()
    logger.info(f"Attempting to get cookies from browser: {browser_name} for service: {service}")

    extractor = CrossPlatformCookieExtractor()

    try:
        cookies = extractor.get_cookies_with_fallback(browser_name)
        if cookies:
            logger.info(f"Successfully retrieved cookies from {browser_name}")
        else:
            logger.error(f"Failed to retrieve cookies from {browser_name}")
            return None
    except Exception as e:
        logger.error(f"An unexpected error occurred while retrieving cookies from {browser_name}: {e}", exc_info=True)
        return None

    # Process cookies for the requested service
    if service == "gemini":
        logger.info("Looking for Gemini cookies (__Secure-1PSID and __Secure-1PSIDTS)...")
        secure_1psid = None
        secure_1psidts = None

        try:
            for cookie in cookies:
                if hasattr(cookie, 'name') and hasattr(cookie, 'value') and hasattr(cookie, 'domain'):
                    if cookie.name == "__Secure-1PSID" and "google" in cookie.domain:
                        secure_1psid = cookie.value
                        logger.info(f"Found __Secure-1PSID: {secure_1psid[:20]}..." if secure_1psid else "Found __Secure-1PSID (empty value)")
                    elif cookie.name == "__Secure-1PSIDTS" and "google" in cookie.domain:
                        secure_1psidts = cookie.value
                        logger.info(f"Found __Secure-1PSIDTS: {secure_1psidts[:20]}..." if secure_1psidts else "Found __Secure-1PSIDTS (empty value)")
        except Exception as e:
            logger.error(f"Error processing cookies: {e}")
            return None

        # If browser-cookie3 missed PSIDTS, try reading Firefox database directly
        if secure_1psid and not secure_1psidts and browser_name == "firefox":
            logger.info("browser-cookie3 found PSID but missed PSIDTS, trying direct database read...")
            try:
                db_path = _get_firefox_cookies_db_path()
                if db_path:
                    ts_val = _read_firefox_cookie_direct(db_path, "__Secure-1PSIDTS")
                    if ts_val:
                        secure_1psidts = ts_val
                        logger.info(f"Found __Secure-1PSIDTS via direct DB read: {secure_1psidts[:20]}...")
            except Exception as e:
                logger.warning(f"Direct Firefox DB read failed: {e}")

        if secure_1psid and secure_1psidts:
            if len(secure_1psid.strip()) == 0 or len(secure_1psidts.strip()) == 0:
                logger.warning("Gemini cookies found but appear to be empty (possibly encrypted).")
                return None
            logger.info("Both Gemini cookies found and appear valid.")
            return secure_1psid, secure_1psidts
        else:
            logger.warning("Gemini cookies not found or incomplete.")
            return None
    else:
        logger.warning(f"Unsupported service: {service}")
        return None


def _get_firefox_cookies_db_path() -> Optional[str]:
    """Find Firefox cookies.sqlite path, including Snap installations."""
    import glob

    home = os.path.expanduser("~")
    # Standard path
    paths = glob.glob(os.path.join(home, ".mozilla", "firefox", "*.default*", "cookies.sqlite"))
    if paths:
        return paths[0]
    # Snap path
    paths = glob.glob(os.path.join(home, "snap", "firefox", "common", ".mozilla", "firefox", "*.default*", "cookies.sqlite"))
    if paths:
        return paths[0]
    return None


def _read_firefox_cookie_direct(db_path: str, cookie_name: str) -> Optional[str]:
    """Read a specific cookie value directly from Firefox's cookies.sqlite."""
    import tempfile, shutil

    try:
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
            tmp_path = tf.name
            shutil.copy2(db_path, tmp_path)

        conn = sqlite3.connect(tmp_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT value FROM moz_cookies WHERE name = ? AND host LIKE '%google%'",
            (cookie_name,)
        )
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            return row[0]
        return None
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def get_deepseek_token_from_browser() -> Optional[str]:
    """
    Auto-extract DeepSeek userToken from browser localStorage.

    DeepSeek stores the auth token in localStorage (not cookies),
    so we need to read browser profile data directly.
    """
    browser_name = CONFIG["Browser"].get("name", "chrome").lower()
    logger.info(f"Attempting to extract DeepSeek token from browser: {browser_name}")

    if browser_name in ("chrome", "google-chrome"):
        token = _get_deepseek_token_from_chromium("google-chrome")
    elif browser_name == "brave":
        token = _get_deepseek_token_from_chromium("brave")
    elif browser_name == "edge":
        token = _get_deepseek_token_from_chromium("microsoft-edge")
    elif browser_name == "firefox":
        token = _get_deepseek_token_from_firefox()
    else:
        logger.warning(f"Unsupported browser for DeepSeek token extraction: {browser_name}")
        return None

    if token:
        logger.info("DeepSeek token successfully extracted from browser.")
        return token

    logger.warning("Could not extract DeepSeek token from browser.")
    return None


def _get_deepseek_token_from_chromium(browser_dir_name: str) -> Optional[str]:
    """
    Extract DeepSeek userToken from Chromium-based browser localStorage (LevelDB).
    """
    home = os.path.expanduser("~")
    leveldb_path = os.path.join(
        home, ".config", browser_dir_name, "Default", "Local Storage", "leveldb"
    )

    if not os.path.isdir(leveldb_path):
        logger.info(f"Chromium LevelDB path not found: {leveldb_path}")
        # Fallback: try snap-based Chrome path
        snap_path = os.path.join(
            home, "snap", browser_dir_name, "current",
            ".config", browser_dir_name, "Default", "Local Storage", "leveldb"
        )
        if os.path.isdir(snap_path):
            leveldb_path = snap_path
        else:
            return None

    # The localStorage key in LevelDB is: _https://chat.deepseek.com\x00\x00userToken
    # We look for the origin marker + key pattern and extract the value nearby.
    origin_marker = b"chat.deepseek.com"
    key_marker = b"userToken"

    for fname in sorted(os.listdir(leveldb_path)):
        if not (fname.endswith(".ldb") or fname.endswith(".log")):
            continue
        fpath = os.path.join(leveldb_path, fname)
        try:
            with open(fpath, "rb") as f:
                data = f.read()
        except OSError:
            continue

        if origin_marker not in data or key_marker not in data:
            continue

        # Token is a long alphanumeric string (JWT-like or base64)
        # Try to find it near "userToken" marker
        idx = data.find(key_marker)
        if idx == -1:
            continue

        # Search forward from userToken for a valid-looking token string
        search_start = idx + len(key_marker)
        chunk = data[search_start:search_start + 300]

        # The token is base64-encoded (may contain +, /, =) or a JWT (dots)
        import re
        matches = re.findall(rb"[A-Za-z0-9_\-\.\+/]{40,}", chunk)
        for m in matches:
            token = m.decode("utf-8", errors="ignore")
            if len(token) >= 40:
                return token

    return None


def _get_deepseek_token_from_firefox() -> Optional[str]:
    """
    Extract DeepSeek userToken from Firefox localStorage (webappsstore.sqlite).
    """
    home = os.path.expanduser("~")
    profiles_path = os.path.join(home, ".mozilla", "firefox")

    if not os.path.isdir(profiles_path):
        return None

    import glob
    profile_dirs = glob.glob(os.path.join(profiles_path, "*.default*")) + \
                   glob.glob(os.path.join(profiles_path, "*.default-release*"))

    for profile_dir in profile_dirs:
        db_path = os.path.join(profile_dir, "webappsstore.sqlite")
        if not os.path.exists(db_path):
            continue
        try:
            import tempfile
            import shutil

            with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
                tmp_path = tf.name
                shutil.copy2(db_path, tmp_path)

            try:
                conn = sqlite3.connect(tmp_path)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT value FROM webappsstore2 "
                    "WHERE scope LIKE '%chat.deepseek%' AND key = 'userToken'"
                )
                row = cursor.fetchone()
                conn.close()
                if row and row[0]:
                    return row[0]
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        except Exception as e:
            logger.warning(f"Failed to read Firefox localStorage: {e}")
            continue

    return None