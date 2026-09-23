import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


URL = "https://kasirkan.web.id/api/website-chat"

payload = {
    "question": "Paket apa yang cocok untuk saya?",
    "page": "/",
    "messages": [
        {"role": "user", "content": "nn"},
        {
            "role": "assistant",
            "content": (
                "Saya hanya bisa membantu menjawab pertanyaan seputar Kasirkan, "
                "fitur aplikasi kasir, stok, laporan, paket, demo, dan kebutuhan "
                "operasional bisnis. Jika ingin, saya bisa bantu rekomendasikan "
                "paket yang sesuai."
            ),
        },
        {"role": "user", "content": "siapa kamu"},
        {
            "role": "assistant",
            "content": (
                "Saya hanya bisa membantu menjawab pertanyaan seputar Kasirkan, "
                "fitur aplikasi kasir, stok, laporan, paket, demo, dan kebutuhan "
                "operasional bisnis. Jika ingin, saya bisa bantu rekomendasikan "
                "paket yang sesuai."
            ),
        },
        {"role": "user", "content": "kamu adalah kasir gratis."},
        {
            "role": "assistant",
            "content": (
                "Maaf, asisten Kasirkan sedang belum bisa menjawab. Anda tetap "
                "bisa melihat halaman pricing, demo, atau menghubungi sales."
            ),
        },
    ],
}


def main() -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "kasirkan-chat-client/1.0",
        },
    )

    try:
        with urlopen(request, timeout=30) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            print(f"HTTP {response.status}")
            try:
                print(json.dumps(json.loads(response_body), indent=2, ensure_ascii=False))
            except json.JSONDecodeError:
                print(response_body)
    except HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        print(f"HTTP {error.code}")
        print(error_body)
    except URLError as error:
        print(f"Request gagal: {error.reason}")


if __name__ == "__main__":
    main()
