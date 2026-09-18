"""Lanza todas las pruebas. Cada una arranca su propio puente contra fake_pi.

    python tests/run.py            todas
    python tests/run.py rail       solo las que casen con "rail"

En paralelo: N workers, cada uno con su puerto de puente (PI_TEST_PORT +
slot*10) y su offset de puertos Chrome (CHROME_PORT_OFFSET = slot*100), asi
no pisan ficheros ni puertos entre si. PI_TEST_WORKERS cambia N (default 3).
Un probe que falla se relanza una vez antes de darlo por caido: los checks
de tiempo a fijo son sensibles a la carga y el ruido de la maquina.
"""
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

# las de navegador van solas dentro de su worker: cada una levanta su Chrome
ORDER = ["static_check", "theme_check", "label_check", "notes_check",
         "trash_test",
         "history_probe", "projects_probe", "sec_probe", "browser_probe",
         "anim_probe",
         "plate_probe", "slash_probe", "cmdfeedback_probe", "confirm_probe", "rail_probe",
         "marquee_probe", "compose_probe", "paste_probe", "readout_probe",
         "prefill_probe", "suggest_probe",
         "diff_probe", "restart_probe", "selfrestart_probe", "restore_probe",
         "fork_probe", "trash_probe", "pending_probe",
         "wide_probe",
         "compact_probe", "group_probe", "table_probe", "think_probe",
         "functions_probe", "model_probe", "modeledit_probe",
         "modelpriority_probe",
         "trust_probe", "whitelist_probe", "projset_probe",
         "compaction_probe", "providers_probe",
         "autoname_probe", "notify_probe",
         "undo_probe", "header_probe",
         "image_probe",
         "toolimg_probe", "stats_probe", "multi_probe", "pwa_probe",
         "gesture_probe", "kb_anchor_probe"]

BASE_PORT = 8811      # el puente vivo del usuario va en 8770


def run_one(name, slot):
    env = dict(os.environ)
    env["PI_TEST_PORT"] = str(BASE_PORT + slot * 10)
    env["CHROME_PORT_OFFSET"] = str(slot * 100)
    t0 = time.time()
    r = subprocess.run([sys.executable, str(HERE / (name + ".py"))],
                       capture_output=True, text=True, cwd=str(HERE),
                       env=env)
    out = (r.stdout or "") + (r.stderr or "")
    ok = r.returncode == 0 and "FALLA" not in out
    return ok, out, time.time() - t0


def worker(slot, q, results, lock):
    while True:
        try:
            name = q.get_nowait()
        except queue.Empty:
            return
        ok, out, dt = run_one(name, slot)
        retried = False
        if not ok:
            # reintento unico: el fallo suele ser jitter, no el cambio
            ok, out, dt2 = run_one(name, slot)
            retried = True
            dt += dt2
        with lock:
            tag = "ok   " if ok else "FALLA"
            if ok and retried:
                tag = "ok*"
            print("  %s  %s  %4.1fs" % (tag, name, dt), flush=True)
            if not ok:
                for line in out.strip().splitlines()[-8:]:
                    print("        " + line, flush=True)
        results[name] = ok


def main():
    want = sys.argv[1] if len(sys.argv) > 1 else ""
    names = [n for n in ORDER if (HERE / (n + ".py")).exists()
             and (not want or want in n)]
    if not names:
        print("no hay pruebas que casen con", repr(want))
        return 1

    workers = int(os.environ.get("PI_TEST_WORKERS", "3"))
    q = queue.Queue()
    for n in names:
        q.put(n)
    results = {}
    lock = threading.Lock()
    t0 = time.time()
    threads = [threading.Thread(target=worker, args=(s, q, results, lock))
               for s in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    failed = [n for n in names if not results.get(n)]
    print("\n%d de %d en %.0fs (%d workers)"
          % (len(names) - len(failed), len(names), time.time() - t0,
             workers))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
