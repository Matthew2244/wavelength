"""Stands in for the real worker in tests: behaviour chosen by the link."""
import json
import sys
import time

task = json.loads(sys.stdin.readline())


def emit(ev, **d):
    d["ev"] = ev
    print(json.dumps(d), flush=True)


url = task.get("spec", {}).get("url", "")
if task["task"] == "probe":
    if "playlist" in url:
        emit("playlist", title="Set", entries=[{"url": "https://ex.com/%d" % i, "title": "Item %d" % i}
                                                for i in range(1, 4)])
    elif "badprobe" in url:
        emit("log", text="ERROR: [youtube] abc: Private video")
        emit("end", ok=False)
        sys.exit()
    else:
        emit("info", title="Title of " + url, duration=61, uploader="Someone", info_file="", size=1000)
    emit("end", ok=True)
elif task["task"] == "download":
    slow = 0.6 if "slow" in url else 0.05
    for k in range(1, 5):
        emit("progress", done=k * 250, total=1000, speed=500, eta=1, part=1, parts=1)
        time.sleep(slow)
    if "fail" in url:
        emit("log", text="ERROR: [generic] Unable to download webpage: HTTP Error 404: Not Found")
        emit("end", ok=False)
    else:
        emit("stage", text="Converting")
        emit("file", path="/tmp/fake/%s.m4a" % url.rsplit("/", 1)[-1])
        emit("end", ok=True)
