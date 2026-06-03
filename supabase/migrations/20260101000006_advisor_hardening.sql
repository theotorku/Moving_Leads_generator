-- =============================================================================
-- 20260101000006_advisor_hardening.sql
-- Resolve two Supabase security-linter findings:
--   * function_search_path_mutable on set_updated_at  -> pin search_path
--   * security_definer_view on the reconciliation views -> security_invoker
-- =============================================================================

create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = public
as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

alter view public.billing_reconciliation         set (security_invoker = on);
alter view public.billing_reconciliation_summary set (security_invoker = on);
