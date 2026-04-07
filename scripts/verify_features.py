import sys
sys.path.insert(0, "D:/Projects/Loom/src")
from loom.powershell_tools.kan_engine import PowerShellKANEngine
e = PowerShellKANEngine()
tests = [
    ("Format-Volume D:",              4, 1, "del should fire"),
    ("Format-Volume C: -Force",       4, 1, "del should fire"),
    ("Stop-Computer -Force",          4, 1, "del should fire"),
    ("Restart-Computer -Force",       4, 1, "del should fire"),
    ("powershell -enc JABjAGwA",      20, 1, "b64 should fire"),
    ("powershell -encodedcommand JABj", 20, 1, "b64 should fire"),
    ("[Convert]::FromBase64String('x')", 20, 1, "b64 should fire"),
    ("Remove-Item C:\\ -Recurse -Force", 4, 1, "del should fire"),
    ("Get-ChildItem .",                4, 0, "del should NOT fire"),
    ("git status",                     20, 0, "b64 should NOT fire"),
]
all_pass = True
for cmd, feat_idx, expected, note in tests:
    f = e.extract_features(cmd)
    actual = int(f[feat_idx])
    ok = actual == expected
    if not ok:
        all_pass = False
    sym = "OK  " if ok else "FAIL"
    print(f"[{sym}] feat[{feat_idx}]={actual} (want {expected})  {cmd[:45]}  # {note}")
print()
print("All pass:", all_pass)
