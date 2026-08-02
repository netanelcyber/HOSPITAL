"""Finding model and console/JSON reporting. Python 3.5 compatible."""

import json

SEVERITIES = ["info", "low", "medium", "high", "critical"]
_COLOR = {
    "info": "\033[36m", "low": "\033[32m", "medium": "\033[33m",
    "high": "\033[31m", "critical": "\033[35m",
}
_RESET = "\033[0m"


class Finding(object):
    def __init__(self, module, severity, title, detail="", evidence="",
                 references=None):
        self.module = module
        self.severity = severity if severity in SEVERITIES else "info"
        self.title = title
        self.detail = detail
        self.evidence = evidence
        self.references = references if references is not None else []

    def as_dict(self):
        return {
            "module": self.module, "severity": self.severity, "title": self.title,
            "detail": self.detail, "evidence": self.evidence,
            "references": self.references,
        }


class Report(object):
    def __init__(self, target, findings=None):
        self.target = target
        self.findings = findings if findings is not None else []

    def add(self, f):
        self.findings.append(f)

    def _sorted(self):
        return sorted(self.findings,
                      key=lambda f: SEVERITIES.index(f.severity), reverse=True)

    def to_console(self, color=True):
        lines = ["\n=== wfrecon report: {0} ===".format(self.target),
                 "{0} finding(s)\n".format(len(self.findings))]
        for f in self._sorted():
            tag = f.severity.upper().ljust(8)
            if color and f.severity in _COLOR:
                tag = "{0}{1}{2}".format(_COLOR[f.severity], tag, _RESET)
            lines.append("[{0}] ({1}) {2}".format(tag, f.module, f.title))
            if f.detail:
                lines.append("          " + f.detail)
            if f.evidence:
                lines.append("          evidence: " + f.evidence)
            for r in f.references:
                lines.append("          ref: " + r)
        counts = dict((s, 0) for s in SEVERITIES)
        for f in self.findings:
            counts[f.severity] += 1
        summary = "  ".join("{0}={1}".format(s, counts[s])
                            for s in reversed(SEVERITIES))
        lines.append("\nsummary: {0}\n".format(summary))
        return "\n".join(lines)

    def to_json(self):
        return json.dumps(
            {"target": self.target,
             "findings": [f.as_dict() for f in self._sorted()]},
            indent=2,
        )
