-- =============================================================================
-- 20260101000014_lead_attribution_fields.sql
-- Break generic provenance into usable acquisition attribution:
-- channel, medium, campaign, referrer, partner, and landing page.
-- =============================================================================

alter table public.leads
    add column if not exists source_channel  text,
    add column if not exists source_medium   text,
    add column if not exists source_campaign text,
    add column if not exists source_referrer text,
    add column if not exists source_partner  text,
    add column if not exists landing_page    text;

update public.leads
set source_channel = case
    when source is null or source = 'public_form' then 'direct'
    else source
end
where source_channel is null;

alter table public.leads
    alter column source_channel set default 'unknown';

create index if not exists leads_source_channel_idx on public.leads (source_channel);
create index if not exists leads_source_campaign_idx on public.leads (source_campaign);
create index if not exists leads_source_partner_idx on public.leads (source_partner);
