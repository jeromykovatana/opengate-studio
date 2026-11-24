/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Coherent-state verdict for ZV-E1 zvread_v4 read-only check/dump (stock preflight vs open-gate applied). */
struct preflight_counts {
    unsigned int other;
    unsigned int cp_og_stock;
    unsigned int cp_og_target;
    unsigned int sr_stock;
    unsigned int sr_target;
    unsigned int sr_runtime;
    unsigned int oz_stock;
    unsigned int oz_target;
    unsigned int oz_runtime;
    unsigned int ozg_stock;
    unsigned int ozg_runtime;
    unsigned int sc0_stock;
    unsigned int sc0_target;
    unsigned int scf_stock;
    unsigned int scf_target;
    unsigned int mp_base_stock;
    unsigned int mp_base_target;
    unsigned int mp_hdr_stock;
    unsigned int mp_hdr_target;
};

static int sp_streq(const char *a, const char *b)
{
    while (*a && *a == *b) {
        a++;
        b++;
    }
    return *a == *b;
}

static int sp_starts_with(const char *s, const char *prefix)
{
    while (*prefix) {
        if (*s++ != *prefix++)
            return 0;
    }
    return 1;
}

static void observe_cp_site(struct preflight_counts *counts, const char *name,
                            int soft, int has_target, int st, int tg)
{
    if (!soft) {
        if (!sp_starts_with(name, "screen")) {
            if (st) counts->cp_og_stock++;
            else if (tg) counts->cp_og_target++;
            else counts->other++;
        } else if (sp_streq(name, "screen0")) {
            if (st) counts->sc0_stock++;
            else if (tg) counts->sc0_target++;
            else counts->other++;
        } else if (sp_streq(name, "screen1") || sp_streq(name, "screen2") ||
                   sp_streq(name, "screen3") || sp_streq(name, "screen4")) {
            if (st) counts->scf_stock++;
            else if (tg) counts->scf_target++;
            else counts->other++;
        } else {
            counts->other++;
        }
        return;
    }

    if (has_target && sp_streq(name, "stored_record")) {
        if (st) counts->sr_stock++;
        else if (tg) counts->sr_target++;
        else counts->sr_runtime++;
    } else if (has_target && sp_streq(name, "outsize")) {
        if (st) counts->oz_stock++;
        else if (tg) counts->oz_target++;
        else counts->oz_runtime++;
    } else if (!has_target && (sp_streq(name, "outsize_guard0") || sp_streq(name, "outsize_guard1"))) {
        if (st) counts->ozg_stock++;
        else if (tg) counts->other++;
        else counts->ozg_runtime++;
    } else {
        counts->other++;
    }
}

static void observe_mp_site(struct preflight_counts *counts, int is_header, int st, int tg)
{
    if (is_header) {
        if (st) counts->mp_hdr_stock++;
        else if (tg) counts->mp_hdr_target++;
        else counts->other++;
    } else {
        if (st) counts->mp_base_stock++;
        else if (tg) counts->mp_base_target++;
        else counts->other++;
    }
}

static const char *preflight_verdict(const struct preflight_counts *c)
{
    if (c->other != 0)
        return "\nVERDICT NOT READY\n";
    if (c->cp_og_stock == 22 && c->cp_og_target == 0 &&
        c->sr_target == 0 && (c->sr_stock + c->sr_runtime == 1) &&
        c->oz_target == 0 && (c->oz_stock + c->oz_runtime == 1) &&
        (c->ozg_stock + c->ozg_runtime == 2) &&
        c->sc0_stock == 1 && c->sc0_target == 0 &&
        c->scf_stock == 4 && c->scf_target == 0 &&
        c->mp_base_stock == 105 && c->mp_base_target == 0 &&
        c->mp_hdr_stock == 8 && c->mp_hdr_target == 0)
        return "\nVERDICT READY (stock preflight)\n";
    if (c->cp_og_target == 22 && c->cp_og_stock == 0 &&
        c->sr_stock == 0 && (c->sr_target + c->sr_runtime == 1) &&
        c->oz_target == 1 && c->oz_stock == 0 &&
        c->ozg_stock == 2 &&
        ((c->sc0_stock == 1 && c->sc0_target == 0 && c->scf_stock == 4 && c->scf_target == 0) ||
         (c->sc0_target == 1 && c->sc0_stock == 0 && c->scf_target == 4 && c->scf_stock == 0) ||
         (c->sc0_stock == 1 && c->sc0_target == 0 && c->scf_target == 4 && c->scf_stock == 0)) &&
        c->mp_base_target == 105 && c->mp_base_stock == 0 &&
        ((c->mp_hdr_target == 0 && c->mp_hdr_stock == 8) ||
         (c->mp_hdr_target == 2 && c->mp_hdr_stock == 6) ||
         (c->mp_hdr_target == 8 && c->mp_hdr_stock == 0)))
        return "\nVERDICT READY (open gate applied)\n";
    return "\nVERDICT NOT READY\n";
}
