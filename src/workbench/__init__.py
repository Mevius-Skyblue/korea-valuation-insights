"""P7-C1 workbench back end: evaluation sessions on top of an auto draft (config/p7c1.yaml).

    spec       assumption fields, range checks, display formatting
    session    create / list / open / clone / delete, data snapshot, versions, audit trail
    recalc     fast engine-only recalculation with an in-memory context (no Excel)
    judge      the ranked judgement list as work items: candidates, direct input, keep; pending count
    confirm    a confirmed version -> session config -> Excel model + report (PC or public mode)
    public     public-mode export rules and the KRX raw-value scan of the outputs

The screen (P7-C2) calls these functions; nothing here talks to KRX or ECOS.
"""
