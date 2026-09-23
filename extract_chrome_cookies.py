import os
import json
import base64
import sqlite3
import shutil
import tempfile
from pathlib import Path
import win32crypt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def get_chrome_encryption_key():
    local_state_path = Path(os.environ["LOCALAPPDATA"]) / "Google" / "Chrome" / "User Data" / "Local State"
    if not local_state_path.exists():
        return None
    with open(local_state_path, "r", encoding="utf-8") as f:
        local_state = json.load(f)
    encrypted_key = base64.b64decode(local_state["os_crypt"]["encrypted_key"])
    # Remove DPAPI prefix 'DPAPI'
    encrypted_key = encrypted_key[5:]
    decrypted_key = win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)[1]
    return decrypted_key

def decrypt_cookie_value(encrypted_val, key):
    try:
        # Chrome v10+ uses AES-256-GCM with 'v10' prefix
        if encrypted_val[:3] == b'v10' or encrypted_val[:3] == b'v11':
            nonce = encrypted_val[3:15]
            ciphertext = encrypted_val[15:]
            aesgcm = AESGCM(key)
            decrypted = aesgcm.decrypt(nonce, ciphertext, None)
            return decrypted.decode('utf-8', errors='ignore')
        else:
            return win32crypt.CryptUnprotectData(encrypted_val, None, None, None, 0)[1].decode('utf-8', errors='ignore')
    except Exception as e:
        return ""

def extract_linkedin_cookies_from_chrome():
    key = get_chrome_encryption_key()
    if not key:
        print("Could not get encryption key")
        return {}

    user_data = Path(os.environ["LOCALAPPDATA"]) / "Google" / "Chrome" / "User Data"
    # Find all cookie files in Default or Profiles
    cookie_paths = list(user_data.glob("Default/Network/Cookies")) + list(user_data.glob("Profile */Network/Cookies")) + list(user_data.glob("Default/Cookies"))
    print("Found cookie paths:", len(cookie_paths))

    all_li_cookies = {}

    for cp in cookie_paths:
        try:
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp_path = tmp.name
            shutil.copy2(str(cp), tmp_path)

            conn = sqlite3.connect(tmp_path)
            cur = conn.cursor()
            rows = cur.execute("SELECT name, encrypted_value, host_key, path FROM cookies WHERE host_key LIKE '%linkedin.com%'").fetchall()
            print(f"Path {cp.parent.parent.name} has {len(rows)} linkedin cookies")

            for name, enc_val, host_key, path in rows:
                val = decrypt_cookie_value(enc_val, key)
                if val:
                    all_li_cookies[name] = {
                        "name": name,
                        "value": val,
                        "domain": host_key,
                        "path": path
                    }
            conn.close()
            os.unlink(tmp_path)
        except Exception as e:
            print(f"Error reading {cp}: {e}")

    return all_li_cookies

if __name__ == "__main__":
    cookies = extract_linkedin_cookies_from_chrome()
    print("Extracted cookie names:", list(cookies.keys()))
    if "li_at" in cookies:
        print("SUCCESS! Found active li_at from Chrome!")
        val = cookies['li_at']['value']
        print(f"li_at prefix: {val[:10]}... length: {len(val)}")
