import subprocess
import json
import urllib.request

# Check listening debug ports
for port in [9222, 9223, 9224, 9229]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as r:
            data = json.loads(r.read().decode())
            print(f"Port {port} is active: {data.get('Browser')}")
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1) as r2:
                pages = json.loads(r2.read().decode())
                print(f"Pages on {port}:", [{"title": p.get("title"), "url": p.get("url")} for p in pages if p.get("url")])
    except Exception:
        pass
