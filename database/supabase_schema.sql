-- Supabase schema — AI Agents Hub
-- ==================================
-- شغّل الملف ده مرة واحدة في Supabase SQL Editor (Project -> SQL Editor -> New query).
--
-- الغرض: Supabase بقى تخزين كامل موازي لـ Google Sheets - نفس تفاصيل
-- الفاتورة اللي بتتكتب في الشيت (بما فيها line_items، اللي اتشالت من
-- الشيت نفسه)، بالإضافة لفحص التكرار (file_hash) اللي كان شغّال على
-- Postgres قبل كده.

create table if not exists invoices (
    id uuid primary key,
    file_hash text not null unique,

    -- مصدر الملف
    source_filename text,
    drive_file_id text,

    -- بيانات الفاتورة (نفس أعمدة sheets_writer.py + line_items)
    vendor_name text,
    invoice_number text,
    invoice_date date,
    due_date date,
    customer_name text,
    customer_address text,
    customer_email text,
    customer_phone text,
    currency text,
    subtotal numeric,
    tax_amount numeric,
    discount numeric,
    total_amount numeric,
    total_due numeric,
    line_items jsonb not null default '[]'::jsonb,

    -- نتيجة الـ Validation
    is_valid boolean,
    validation_errors jsonb not null default '[]'::jsonb,

    -- حالة المزامنة مع Google Sheets
    sheets_synced boolean not null default true,

    created_at timestamptz not null default now()
);

-- فهرس على file_hash عشان is_duplicate() تكون سريعة (unique constraint
-- فوق بيعمل الفهرس ده تلقائيًا فعليًا، هنا بس توضيح/تأكيد).
create index if not exists idx_invoices_file_hash on invoices (file_hash);

-- فهرس على vendor_name عشان أي بحث/فلترة لاحقة على المورد تبقى سريعة
create index if not exists idx_invoices_vendor_name on invoices (vendor_name);

-- Only the backend service role should access customer invoice records.
alter table invoices enable row level security;
revoke all on table invoices from anon, authenticated;
