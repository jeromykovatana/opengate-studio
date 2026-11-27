import Foundation

/// Source of the active safety session state used by `QuickReapplyPlanner`.
public enum QuickReapplyResultSource: String, Equatable, Sendable {
    case mock
    case liveInApp
    case liveTerminal
}

/// Deterministic decision for the one-click "Quick Field Re-Apply (Safe Daily 3:2)" workflow.
public enum QuickReapplyDecision: Equatable, Sendable {
    /// SHA-256 kit pins failed or have not yet been verified; live actions are blocked.
    case blockedPinsUnverified
    /// A leftover helper warning, failed/interrupted session, or unverified closing state exists.
    case runRecoveryPreflightFirst
    /// No fresh verified `live_usb` `stock` preflight exists (e.g. after a battery swap or mock-only run).
    case runPreflightThenSafeDailyApply
    /// A verified `live_usb` `stock` preflight is active; ready to prompt live Safe Daily 3:2 apply.
    case readyForSafeDailyApply(packs: [String])
    /// Camera RAM is already recorded as verified `applied` in the active live session.
    case alreadyApplied
}

/// Pure, deterministic planner for Safe Daily 3:2 field re-apply after a battery swap.
///
/// Safety invariants:
/// - Never bypasses live `stock` preflight before live apply.
/// - Offline mock simulation (`offlineMockCamera == true`, `resultSource == .mock`,
///   or `latestSession?.mode == "mock"`) NEVER unlocks live apply or counts as live applied.
/// - Interrupted, unverified, or `leftBehindWarning` sessions always require recovery preflight first.
public enum QuickReapplyPlanner {
    public static let safeDailyPacks: [String] = ["mp4_3x2", "screen_3x2"]

    private static let unverifiedStates: Set<String> = [
        "not_ready",
        "unverified",
        "applied_unverified",
        "stock_unverified",
    ]

    public static func plan(
        pinsVerified: Bool,
        selectedBodyId: String? = nil,
        offlineMockCamera: Bool = false,
        leftBehindWarning: Bool = false,
        hasInterruptedSession: Bool = false,
        preflightResult: PreflightResult? = nil,
        applyResult: ApplyResult? = nil,
        putbackResult: PutbackResult? = nil,
        latestSession: LatestSessionResult? = nil,
        resultSource: QuickReapplyResultSource? = nil
    ) -> QuickReapplyDecision {
        guard pinsVerified else {
            return .blockedPinsUnverified
        }

        if leftBehindWarning || hasInterruptedSession {
            return .runRecoveryPreflightFirst
        }

        func matchesSelectedBody(_ candidateBodyId: String?) -> Bool {
            guard let selectedBodyId, !selectedBodyId.isEmpty else { return true }
            guard let candidateBodyId, !candidateBodyId.isEmpty else { return true }
            return candidateBodyId == selectedBodyId
        }

        let liveSession: LatestSessionResult? = {
            guard let ls = latestSession,
                  ls.found,
                  ls.mode == "live_usb",
                  matchesSelectedBody(ls.bodyId) else {
                return nil
            }
            return ls
        }()

        if let ls = liveSession {
            if !ls.ok || !ls.ready || ls.verified == false || unverifiedStates.contains(ls.state) {
                return .runRecoveryPreflightFirst
            }
            if (ls.kind == "putback" || ls.kind == "express_putback") && ls.state != "stock" {
                return .runRecoveryPreflightFirst
            }
            if (ls.kind == "apply" || ls.kind == "closing_dump" || ls.kind == "express_apply") && ls.state != "applied" {
                return .runRecoveryPreflightFirst
            }
        }

        let isMockOrigin = offlineMockCamera || resultSource == .mock || latestSession?.mode == "mock"

        if !isMockOrigin {
            if let pre = preflightResult, matchesSelectedBody(pre.bodyId) {
                if !pre.ok || !pre.ready || unverifiedStates.contains(pre.state) {
                    return .runRecoveryPreflightFirst
                }
            }
            if let put = putbackResult, matchesSelectedBody(put.bodyId) {
                if !put.ok || put.state != "stock" {
                    return .runRecoveryPreflightFirst
                }
            }
            if let app = applyResult, matchesSelectedBody(app.bodyId) {
                if !app.ok {
                    return .runRecoveryPreflightFirst
                }
            }
        }

        // Mock READY or mock applied must NEVER unlock live apply or claim live applied state.
        if isMockOrigin {
            return .runPreflightThenSafeDailyApply
        }

        let hasLiveSource = (resultSource == .liveInApp || resultSource == .liveTerminal)

        if let ls = liveSession {
            let isVerifiedAppliedKind = ls.kind == "closing_dump" || ls.kind == "express_apply" || ls.kind == "apply"
            if (isVerifiedAppliedKind || ls.state == "applied") && ls.state == "applied" && ls.ok && ls.ready && ls.verified != false {
                return .alreadyApplied
            }
            let isPreflightKind = (ls.kind == "preflight" || ls.kind == "dump")
            if isPreflightKind && ls.ok && ls.ready && ls.verified != false && ls.state == "stock" {
                if let pre = preflightResult, matchesSelectedBody(pre.bodyId) {
                    guard pre.ok && pre.ready && pre.state == "stock" else {
                        return .runPreflightThenSafeDailyApply
                    }
                }
                return .readyForSafeDailyApply(packs: safeDailyPacks)
            }
            // e.g. latest live session is a verified putback (kind == "putback", state == "stock"):
            // CLI still requires a fresh preflight/dump session before apply.
            return .runPreflightThenSafeDailyApply
        }

        if hasLiveSource {
            if let app = applyResult, matchesSelectedBody(app.bodyId), app.ok {
                return .alreadyApplied
            }
            if let pre = preflightResult, matchesSelectedBody(pre.bodyId), pre.ok, pre.ready {
                if pre.state == "applied" {
                    return .alreadyApplied
                }
                if pre.state == "stock" && putbackResult == nil {
                    return .readyForSafeDailyApply(packs: safeDailyPacks)
                }
            }
        }

        return .runPreflightThenSafeDailyApply
    }
}
