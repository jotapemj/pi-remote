"""Lanza todas las pruebas. Cada una arranca su propio puente contra fake_pi.

    python tests/run.py            todas
    python tests/run.py rail       solo las que casen con "rail"
"""
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

# las de navegador van de una en una: cada una levanta su Chrome
ORDER = ["static_check", "theme_check", "notes_check", "trash_test",
         "history_probe", "projects_probe", "sec_probe", "browser_probe",
         "anim_probe",
         "plate_probe", "slash_probe", "cmdfeedback_probe", "confirm_probe", "rail_probe",
         "marquee_probe", "compose_probe", "paste_probe", "readout_probe",
         "prefill_probe", "suggest_probe",
         "diff_probe", "restart_probe", "restore_probe", "pending_probe",
         "wide_probe",
         "compact_probe", "group_probe", "table_probe", "think_probe",
         "functions_probe", "undo_probe", "header_probe", "image_probe",
         "toolimg_probe", "stats_probe", "multi_probe", "pwa_probe",
         "gesture_probe", "kb_anchor_probe"]


def main():
    want = sys.argv[1] if len(sys.argv) > 1 else ""
    names = [n for n in ORDER if (HERE / (n + ".py")).exists()
             and (not want or want in n)]
    if not names:
        print("no hay pruebas que casen con", repr(want))
        return 1

    width = max(len(n) for n in names)
    failed = []
    t0 = time.time()
    for name in names:
        started = time.time()
        r = subprocess.run([sys.executable, str(HERE / (name + ".py"))],
                           capture_output=True, text=True, cwd=str(HERE))
        out = (r.stdout or "") + (r.stderr or "")
        ok = r.returncode == 0 and "FALLA" not in out
        print("  %s  %-*s  %4.1fs" % ("ok   " if ok else "FALLA",
                                      width, name, time.time() - started))
        if not ok:
            failed.append(name)
            for line in out.strip().splitlines()[-8:]:
                print("        " + line)

    print("\n%d de %d en %.0fs" % (len(names) - len(failed), len(names),
                                   time.time() - t0))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
