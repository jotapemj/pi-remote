"""Bloque de arranque: los enlaces por donde se sirve el puente.

Unidad pura sobre serve_links con direcciones inventadas: la de Tailscale
va primero (es la del movil), localhost siempre, la red de casa si hay, y
el adaptador de WSL (172.16/12) y el loopback no salen.
"""
import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from harness import report  # noqa: E402
import pi_web_bridge as b   # noqa: E402


def main():
    full = b.serve_links(8770, "TK", origins=[],
                         addrs=["127.0.0.1", "172.29.172.127",
                                "100.101.102.103", "192.168.1.20",
                                "100.101.102.103", "basura"])
    print("  completo:", full)
    alone = b.serve_links(8770, "TK", ["172.29.1.1"], origins=[])
    print("  sin tailscale:", alone)
    bare = b.serve_links(9000, "", ["100.100.1.2"], origins=[])
    print("  sin token:", bare)

    https = b.serve_links(8770, "TK", ["100.101.102.103"],
                          origins=["https://pc.tail.ts.net/", "http://x"])
    print("  con https:", https)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        b.print_links()
    text = out.getvalue()
    print(text)
    return [
        ("tailscale primero, con IP y token (no *.ts.net)",
         full[0] == ("Phone (Tailscale)",
                     "http://100.101.102.103:8770/?token=TK")),
        ("localhost siempre", ("This PC", "http://localhost:8770/?token=TK")
         in full and alone == [("This PC",
                                "http://localhost:8770/?token=TK")]),
        ("la red de casa sale", ("Local network",
                                 "http://192.168.1.20:8770/?token=TK") in full),
        ("ni WSL, ni loopback, ni repetidas, ni basura", len(full) == 3),
        ("sin token, sin ?token=",
         bare[0][1] == "http://100.100.1.2:9000/"),
        ("un origen https (tailscale serve) va primero, sin barra doble",
         https[0] == ("Phone (HTTPS)", "https://pc.tail.ts.net/?token=TK")
         and https[1][0] == "Phone (Tailscale)"),
        ("un origen http no cuenta como https",
         not any("http://x" in u for _, u in https)),
        ("el bloque impreso lleva localhost y el aviso",
         "http://localhost:" in text and "keep the link private" in text),
    ]


raise SystemExit(report(main()))
