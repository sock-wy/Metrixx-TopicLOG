import json, threading, time, urllib.request, urllib.error, pathlib, sys, datetime as dt

UA = {"User-Agent": "Mozilla/5.0 (Metrixx TopicLog backfill)", "Accept": "application/json"}
OUT = pathlib.Path(__file__).resolve().parents[2] / "data" / "backfill"   # git-ignored (data/)
OUT.mkdir(parents=True, exist_ok=True)


class Limiter:
    def __init__(self, per_sec):
        self.gap, self.lock, self.next = 1.0 / per_sec, threading.Lock(), 0.0

    def wait(self):
        with self.lock:
            now = time.time()
            t = max(now, self.next)
            self.next = t + self.gap
        time.sleep(max(0, t - now))


def get_json(url, limiter=None, headers=None, tries=6, timeout=60):
    for i in range(tries):
        if limiter:
            limiter.wait()
        try:
            req = urllib.request.Request(url, headers={**UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 403, 404, 422):
                return None
            wait = int(e.headers.get("Retry-After") or 0) or min(60, 2 ** (i + 1))
            time.sleep(wait)
        except Exception:
            time.sleep(min(60, 2 ** (i + 1)))
    return None


def log(name, msg):
    line = f"{dt.datetime.utcnow():%H:%M:%S} [{name}] {msg}"
    print(line, flush=True)
    with open(OUT / f"{name}.log", "a") as f:
        f.write(line + "\n")


def f(x):
    try:
        return None if x in (None, "") else float(x)
    except (TypeError, ValueError):
        return None
