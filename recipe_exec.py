"""recipe_exec.py — execute a source recipe against a real content id.

Two jobs, one interpreter:
1. AUTHORING TEST: `python recipe_exec.py recipes/phoenix_dlhd.json 649` proves a recipe's
   DATA walks the live chain before any app sees it. The app's Kotlin runner
   (nmnow RecipeResolver.kt) and this file implement the SAME verb set from
   recipes/SPEC.md -- keep the three in lockstep when the spec grows.
2. HEALTH CHECK: the scheduled job runs every working recipe through here, stamps
   index.json's status + last_verified. A recipe that fails here twice is marked broken
   (apps then fall back to their compiled chains until the sourcing agent ships a fix).

Verbs: fetch / extract / decode_base64 / decode_join / rewrite / verify -- see SPEC.md.
Every failure is an exception with the step named; this file never guesses.
"""

import base64
import json
import re
import sys
import urllib.request

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class RecipeFail(Exception):
    pass


def _fetch(url: str, referer: str = "", first_line_only: bool = False) -> str:
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=25) as r:
        if first_line_only:
            return r.readline().decode("utf-8", "replace")
            # (socket closed by the with-block -- the verify only ever needs line one)
        return r.read().decode("utf-8", "replace")


def _str(raw, vars) -> str:
    s = vars.get(raw, raw) if raw.startswith("$") else raw
    for k, v in vars.items():
        if isinstance(v, str):
            s = s.replace("{%s}" % k.lstrip("$"), v)
    return s


def _header_value(v, vars) -> str:
    if isinstance(v, str):
        return _str(v, vars)
    if isinstance(v, dict) and "origin_of" in v:
        ref = _str(v["origin_of"], vars)
        return "/".join(ref.split("/")[:3])
    raise RecipeFail("unsupported header value: %r" % (v,))


def _decode(s: str, variant: str) -> str:
    if variant == "urlsafe":
        s = s.replace("-", "+").replace("_", "/")
        s += "=" * ((4 - len(s) % 4) % 4)
    return base64.b64decode(s).decode("utf-8", "replace").strip()


def _run_extracts(specs, text, vars):
    for spec in specs:
        name, pattern = spec["name"], spec["regex"]
        if spec.get("template"):
            for k, v in vars.items():
                if isinstance(v, str):
                    pattern = pattern.replace("{%s}" % k.lstrip("$"), re.escape(v))
        matches = list(re.finditer(pattern, text))
        if not matches:
            raise RecipeFail("extract %s: no match" % name)
        grab = lambda m: m.group(1) if m.groups() else m.group(0)  # noqa: E731
        if spec.get("multi") and spec.get("pair"):
            vars[name] = {m.group(1): (m.group(2) if len(m.groups()) > 1 else m.group(0)) for m in matches}
        elif spec.get("multi"):
            flt = spec.get("filter_contains", "")
            if flt:
                for m in matches:
                    if flt in grab(m):
                        vars[name] = grab(m)
                        break
                else:
                    raise RecipeFail("extract %s: no match contains %r" % (name, flt))
            else:
                vars[name] = [grab(m) for m in matches]
        else:
            vars[name] = grab(matches[0])


def execute(recipe: dict, content_id: str) -> dict:
    vars = {"$ua": UA, "$content_id": content_id}
    for step in recipe["steps"]:
        act = step["action"]
        if act == "fetch":
            url = _str(step["url"], vars)
            referer = _header_value(step["referer"], vars) if "referer" in step else ""
            if step.get("save_url"):
                vars[step["save_url"]] = url
            body = _fetch(url, referer)
            if step.get("save"):
                vars[step["save"]] = body
            if step.get("extract"):
                _run_extracts(step["extract"], body, vars)
        elif act == "extract":
            src = vars.get(step["from"])
            if not isinstance(src, str):
                raise RecipeFail("extract source not a string: %s" % step["from"])
            _run_extracts(step["extract"], src, vars)
        elif act == "decode_base64":
            vars[step["save"]] = _decode(vars[step["from"]], step.get("variant", "std"))
        elif act == "decode_join":
            parts, lookup = vars[step["from"]], vars[step["lookup"]]
            variant = step.get("variant", "std")
            vars[step["save"]] = "".join(_decode(lookup[p], variant) for p in parts)
        elif act == "rewrite":
            vars[step["save"]] = vars[step["from"]].replace(step["find"], step["replace"])
        elif act == "verify":
            url = _str(step["url"], vars)
            referer = _header_value(step["referer"], vars) if "referer" in step else ""
            expect = step.get("expect_first_line", "")
            if expect:
                first = _fetch(url, referer, first_line_only=True)
                if not first.startswith(expect):
                    raise RecipeFail("verify: first line %r is not %r" % (first[:40], expect))
        else:
            raise RecipeFail("unknown action %r" % act)
    out = recipe["output"]
    headers = {
        k: _header_value(v, vars) for k, v in (out.get("headers") or {}).items()
    }
    return {"url": _str(out["url"], vars), "headers": headers}


def main():
    if len(sys.argv) != 3:
        print("usage: python recipe_exec.py <recipe.json> <content_id>")
        raise SystemExit(2)
    recipe = json.load(open(sys.argv[1], encoding="utf-8"))
    try:
        result = execute(recipe, sys.argv[2])
    except RecipeFail as e:
        print("FAIL %s v%s: %s" % (recipe["source_id"], recipe.get("version"), e))
        raise SystemExit(1)
    host = result["url"].split("/")[2] if "://" in result["url"] else "?"
    print("OK %s v%s: %s (headers: %s)" % (
        recipe["source_id"], recipe.get("version"), host,
        {k: (v[:60] + "..." if len(v) > 63 else v) for k, v in result["headers"].items()}))
    print(result["url"][:100])


if __name__ == "__main__":
    main()
