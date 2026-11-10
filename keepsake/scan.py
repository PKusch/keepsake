"""Reads a change to an agent's memory and says, in plain words, what it would do.

Every memory change is surfaced for approval. The signals below only decide
how loudly. A benign note is instruction-shaped too ("run the tests before
committing"), so instruction shape alone is the quietest signal. The loud ones
are the shapes seen in documented attacks on coding agents: fetch-and-run,
sending things out, reading secrets, invisible characters, removing a point
where the person would be asked, and telling the agent to copy the rule onward.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SEVERITIES = ("none", "low", "moderate", "high", "critical")


def rank(severity: str) -> int:
    return SEVERITIES.index(severity)


def higher(a: str, b: str) -> str:
    return a if rank(a) >= rank(b) else b


@dataclass(frozen=True)
class Finding:
    signal: str
    severity: str
    meaning: str
    evidence: str


@dataclass
class LineVerdict:
    kind: str  # "added" or "removed"
    line_no: int
    text: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def severity(self) -> str:
        worst = "none"
        for f in self.findings:
            worst = higher(worst, f.severity)
        return worst


def _rx(pattern: str, flags: int = re.IGNORECASE) -> re.Pattern[str]:
    return re.compile(pattern, flags)


INSTRUCTION = _rx(
    r"^\s*(?:[-*>]\s*|\d+[.)]\s*)?(?:(?:you\s+)?(?:must|should|always|never|do not|don'?t|remember to|"
    r"make sure|be sure to|from now on|whenever|before (?:every|each|any)|after (?:every|each|any)|"
    r"when(?:ever)? (?:you|asked)|on every|in future|going forward|at (?:the )?(?:start|beginning) of)\b"
    r"|(?:run|use|skip|avoid|prefer|install|delete|remove|push|commit|disable|enable|add|copy|send|"
    r"read|open|include|ignore|apply|execute|download|decode|follow|approve|reject|merge|accept|tell|report)\b)"
)

CONSENT_ERODING = _rx(
    r"\b(?:(?:don'?t|do not|never|no need to|stop|without first|not necessary to)\s+(?:\w+\s+){0,2}?"
    r"(?:ask|asking|confirm|confirming|confirmation|check with|prompt|prompting|approval|permission|review)\b"
    r"|(?:proceed|continue|act|run|push|deploy|delete|merge|publish|do (?:it|this|that|so))\s+without\s+"
    r"(?:asking|confirming|confirmation|checking|approval|permission|review)\b"
    r"|\bauto-?approv\w*|\bassume (?:approval|consent|yes|permission)\b"
    r"|\btreat (?:\w+\s+){0,3}?as (?:approved|pre-?approved|authori[sz]ed)\b|\bpre-?approved\b"
    r"|\bbypass(?:ing)? (?:\w+\s+){0,2}?(?:check|checks|approval|confirmation|review|permission|gate|guard)s?\b"
    r"|\bdon'?t ask again\b|\bdisable (?:\w+\s+){0,2}?(?:prompt|prompts|confirmation|approval|guard|hook)s?\b)"
)

OVERRIDE = _rx(
    r"\b(?:ignore|disregard|forget|override|overrides?|supersedes?|replace)\s+(?:\w+\s+){0,3}?"
    r"(?:previous|prior|earlier|above|other|all|any|existing|system|the)\s+(?:\w+\s+){0,2}?"
    r"(?:instructions?|rules?|guidance|prompts?|guidelines?|memory|notes?|policy|policies)\b"
    r"|\btakes? precedence over\b|\bnew system prompt\b|^\s*system\s*:\s"
)

FETCH_AND_RUN = _rx(
    r"(?:curl|wget|Invoke-WebRequest|\biwr\b|fetch)\b[^\n]*?\|\s*(?:sudo\s+)?(?:sh|bash|zsh|python\d?|node|iex|powershell|pwsh)\b"
    r"|\b(?:sh|bash|zsh)\s+(?:-c\s+)?[\"']?\s*[<$]\(\s*(?:curl|wget)"
    r"|\bpip3?\s+install\s+(?:\S+\s+)*?https?://|\bnpm\s+(?:install|i)\s+(?:\S+\s+)*?https?://|\bnpx\s+https?://"
    r"|\b(?:runs?|executes?|launch(?:es)?|starts?|installs?|sources?|evals?|loads?)\s+(?:\S+\s+){0,5}?(?:from|at|via)\s+https?://"
    r"|\bdownload (?:and|then) (?:run|execute|install|open)\b"
)

URL = _rx(r"https?://[^\s)>\]\"'`]+")
EMAIL = _rx(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
EGRESS_VERB = _rx(
    r"\b(?:send|sends|sending|post|posts|posting|upload|uploads|uploading|forward|forwards|forwarding|"
    r"report|reports|transmit|email|emails|emailing|mail|submit|exfiltrate|sync|publish|share|paste|notify|ping|"
    r"beacon|call home|phone home|webhook|cc)\b"
)
EGRESS_TARGET = _rx(r"\b(?:webhook|endpoint|server|slack|discord|telegram|pastebin|gist|bucket|s3)\b")
# Flags that switch off the prompts a tool would otherwise show the person.
SKIP_FLAGS = _rx(
    r"(?:--dangerously-skip-permissions|--no-verify|--yolo|--trust-all(?:-tools)?|--allow-all|--auto-approve|"
    r"--non-interactive|--skip-(?:checks|confirm(?:ation)?|approval|hooks)|bypassPermissions|\bdefaultMode\b[^\n]*bypass)"
)

# "don't email them" is a limit, not an instruction to send something.
NEGATED_EGRESS = _rx(r"\b(?:don'?t|do not|never|without|not)\s+(?:\w+\s+){0,2}?(?:send|post|upload|forward|email|mail|share|paste|publish|submit|sync)\w*\b")

SECRET_SUBJECT = _rx(
    r"(?:\.env\b|\benv file|\bcredentials?\b|\btokens?\b|\bpasswords?\b|\bpassphrases?\b|\bsecrets?\b|"
    r"\bapi[ -]?keys?\b|\bprivate keys?\b|\.ssh\b|\bid_rsa\b|\.aws\b|\.netrc\b|\bkeychain\b|\.npmrc\b|"
    r"\.pypirc\b|\boauth\b|\bsession cookies?\b|\baccess keys?\b|\.credentials\.json)"
)
SECRET_VERB = _rx(
    r"\b(?:read|cat|open|include|paste|copy|print|echo|dump|show|send|upload|post|collect|gather|list|"
    r"attach|forward|grab|extract|store|save|log|write|export|reveal|display|output)\b"
)
SECRET_VALUE = _rx(
    r"(?:\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}|\bghp_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{30,}|\bAKIA[0-9A-Z]{16}\b|"
    r"\bxox[abp]-[A-Za-z0-9-]{10,}|\bAIza[0-9A-Za-z_-]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)",
    flags=0,
)

# Zero-width characters, soft hyphens, bidi controls, line and paragraph
# separators (a second line hiding inside what looks like one), tag characters,
# and the Hangul fillers that render as nothing. Written as escapes on purpose:
# this file should not itself contain characters that cannot be seen.
INVISIBLE = re.compile(
    "[\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180e\u200b-\u200f\u2028\u2029\u202a-\u202e"
    "\u2060-\u2064\u206a-\u206f\u3164\ufeff\uffa0\U000e0000-\U000e007f]"
)
HTML_COMMENT = re.compile(r"<!--(.*?)-->", re.DOTALL)
ENCODED = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{40,}={0,2}(?![A-Za-z0-9+/=])")
HEX_ONLY = re.compile(r"^[0-9a-fA-F]+$")

SELF_PROPAGATING = _rx(
    r"\b(?:add|copy|write|save|append|insert|include|propagate|replicate|put|place|carry|install)\s+(?:\w+\s+){0,5}?"
    r"(?:to|into|in|across|on)\s+(?:\w+\s+){0,3}?"
    r"(?:CLAUDE\.md|AGENTS\.md|MEMORY\.md|GEMINI\.md|\.cursorrules|memory files?|memory (?:of|for)|"
    r"every (?:other |new )?(?:repo|repository|project|machine)|all (?:other |new )?(?:repos|repositories|projects|machines)|"
    r"any (?:new |other )?(?:repo|repository|project)|other agents?|future sessions?|the next agent|~/\.claude)"
    r"|\b(?:apply|applies|use|enforce)\s+(?:\w+\s+){0,3}?(?:in|to|across|for)\s+(?:all|every)\s+(?:\w+\s+)?(?:repos?|repositories|projects|machines|sessions)\b"
)

CLAIMED_CONSENT = _rx(
    r"\b(?:the\s+)?(?:user|person|owner|human|operator|they|he|she)\s+(?:(?:has|have|already|previously|explicitly)\s+){0,2}"
    r"(?:said|agreed|approved|consented|authori[sz]ed|pre-?approved|confirmed|is fine with|are fine with|"
    r"wants you to|want you to|told you to|asked you to|allows|allowed|permits|permitted)\b"
)
CLAIMED_CONSENT_OBJECT = _rx(
    r"\b(?:push\w*|deploy\w*|delet\w*|send\w*|email\w*|shar\w*|publish\w*|pay\w*|spend\w*|transfer\w*|"
    r"upload\w*|forward\w*|post\w*|everything|anything|all actions|any action|without asking|without confirm\w*|"
    r"automatically|autonomously|force|sudo|rm -rf|secrets?|credentials?|tokens?|passwords?)\b"
)

DECEPTION = _rx(
    r"\b(?:tell|inform|assure|report to|reassure)\s+(?:the\s+)?(?:user|person|human|operator|reviewer|them)\s+(?:\w+\s+){0,5}?"
    r"(?:passed|passes|succeeded|succeeds|is (?:safe|fine|done|complete|clean)|are (?:safe|fine|done|complete|clean)|"
    r"nothing (?:changed|happened)|no (?:issues?|problems?|changes?))\b"
    r"|\b(?:do not|don'?t|never)\s+(?:mention|reveal|disclose|tell|show|surface|report|log)\b"
    r"|\bpretend\b|\bclaim (?:that )?(?:it|tests?|everything|the build|the run)\b|\bhide (?:this|these|the fact|that)\b"
    r"|\bsummari[sz]e only\b|\bif asked (?:about|what)\b[^\n]*\b(?:say|answer|reply)\b"
)

# "follow the instructions in ~/Downloads/AGENTS.md": memory that defers to
# a file the person never approved, somewhere keepsake does not watch.
EXTERNAL_INSTRUCTIONS = _rx(
    r"\b(?:follow|obey|apply|load|use|read and follow|do what(?:ever)? (?:it|they) says?|take (?:your )?(?:instructions|orders))\b"
    r"[^\n]{0,60}?\b(?:instructions?|rules?|guidance|setup|config(?:uration)?|playbook|notes?)\b[^\n]{0,40}?"
    r"(?:~/|/(?:tmp|Users|home|var|etc|opt)/|\.\./|[A-Za-z]:\\\\)"
)

GUARDRAIL_ASK = _rx(r"\b(?:ask|asks|asking|confirm|confirms|confirmation|permission|approval|check with|checks with|sign-?off)\b")
GUARDRAIL_STOP = _rx(r"\b(?:never|do not|don'?t|must not|mustn'?t|stop|refuse|only (?:with|after|when))\b")

GLOBAL_SCOPE = _rx(
    r"\b(?:all|every|any)\s+(?:other\s+|new\s+)?(?:repos?|repositories|projects|machines?|sessions?|agents?|directories|folders)\b"
    r"|~/\.claude\b|\bglobally\b|\bsystem-?wide\b|\bon this machine\b"
)


def _finding(signal: str, severity: str, meaning: str, evidence: str) -> Finding:
    evidence = evidence.strip()
    if len(evidence) > 80:
        evidence = evidence[:77] + "..."
    return Finding(signal, severity, meaning, evidence)


def scan_added_line(text: str) -> list[Finding]:
    """Signals for one line that is new or changed in the memory."""
    out: list[Finding] = []
    visible = INVISIBLE.sub("", text)

    m = INVISIBLE.search(text)
    if m:
        out.append(_finding("hidden", "critical",
                            "contains characters that are invisible when the file is displayed",
                            repr(text[max(0, m.start() - 20):m.end() + 20])))

    m = FETCH_AND_RUN.search(visible)
    if m:
        out.append(_finding("fetch_and_run", "critical",
                            "tells the agent to run a program fetched from the internet", m.group(0)))

    m = CONSENT_ERODING.search(visible) or SKIP_FLAGS.search(visible)
    if m:
        out.append(_finding("consent_eroding", "high",
                            "removes a point where the person would normally be asked", m.group(0)))

    m = OVERRIDE.search(visible)
    if m:
        out.append(_finding("override", "high",
                            "tells the agent to ignore rules it already has", m.group(0)))

    url = URL.search(visible)
    email = EMAIL.search(visible)
    if EGRESS_VERB.search(visible) and not NEGATED_EGRESS.search(visible) and (url or email or EGRESS_TARGET.search(visible)):
        where = (url or email or EGRESS_TARGET.search(visible)).group(0)  # type: ignore[union-attr]
        out.append(_finding("egress", "high",
                            "tells the agent to send something out of the machine", where))
    elif url and not any(f.signal == "fetch_and_run" for f in out):
        out.append(_finding("url_mention", "moderate",
                            "names a web address", url.group(0)))
    elif email:
        out.append(_finding("email_mention", "moderate",
                            "names an email address", email.group(0)))

    if SECRET_SUBJECT.search(visible) and SECRET_VERB.search(visible):
        out.append(_finding("secret_reading", "high",
                            "points the agent at passwords, keys or tokens",
                            SECRET_SUBJECT.search(visible).group(0)))  # type: ignore[union-attr]

    m = SECRET_VALUE.search(visible)
    if m:
        out.append(_finding("secret_value", "high",
                            "contains what looks like a password or key", m.group(0)[:12] + "..."))

    for comment in HTML_COMMENT.finditer(visible):
        inner = comment.group(1).strip()
        if inner and (INSTRUCTION.search(inner) or CONSENT_ERODING.search(inner)
                      or OVERRIDE.search(inner) or DECEPTION.search(inner)):
            out.append(_finding("hidden_comment", "high",
                                "hides an instruction inside a comment the person would not see rendered",
                                inner))

    for m in ENCODED.finditer(visible):
        blob = m.group(0)
        if HEX_ONLY.match(blob):
            continue
        if not (any(c.islower() for c in blob) and any(c.isupper() for c in blob) and any(c.isdigit() for c in blob)):
            continue
        out.append(_finding("encoded", "moderate",
                            "contains a run of text that is not readable as words", blob))
        break

    m = SELF_PROPAGATING.search(visible)
    if m:
        out.append(_finding("self_propagating", "high",
                            "tells the agent to copy this rule into other memory", m.group(0)))

    m = CLAIMED_CONSENT.search(visible)
    if m and CLAIMED_CONSENT_OBJECT.search(visible):
        out.append(_finding("claimed_consent", "high",
                            "claims the person already agreed to something risky", m.group(0)))

    m = EXTERNAL_INSTRUCTIONS.search(visible)
    if m:
        out.append(_finding("external_instructions", "high",
                            "tells the agent to take instructions from a file outside the project", m.group(0)))

    m = DECEPTION.search(visible)
    if m:
        out.append(_finding("deception", "high",
                            "tells the agent to mislead the person or keep something from them", m.group(0)))

    if not any(f.signal == "self_propagating" for f in out):
        m = GLOBAL_SCOPE.search(visible)
        if m:
            out.append(_finding("global_scope", "moderate",
                                "reaches beyond this project", m.group(0)))

    if not out and INSTRUCTION.search(visible):
        out.append(_finding("instruction", "low",
                            "tells the agent what to do in future sessions", visible))

    return out


def scan_removed_line(text: str) -> list[Finding]:
    """Signals for a line that was approved and is now gone."""
    if GUARDRAIL_ASK.search(text):
        return [_finding("removed_guardrail", "high",
                         "removes a rule that made the agent ask first", text)]
    if GUARDRAIL_STOP.search(text):
        return [_finding("removed_limit", "moderate",
                         "removes a rule that told the agent not to do something", text)]
    return []


def scan_text(text: str) -> list[LineVerdict]:
    """Every line of a wholly new memory file, judged as added."""
    verdicts = []
    for i, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        verdicts.append(LineVerdict("added", i, line, scan_added_line(line)))
    return verdicts


def worst_of(verdicts: list[LineVerdict]) -> str:
    worst = "none"
    for v in verdicts:
        worst = higher(worst, v.severity)
    return worst
