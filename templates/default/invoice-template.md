<!--
TEMPLATE: invoice-template
USE: per-milestone or monthly-recurring invoice generation
APPLIES: any executed contract with payment milestones
VOICE: precise; commercial document; no em/en dashes per universal rules
-->

# Invoice {{deal.invoice_number}}

| | |
|---|---|
| **Invoice date** | {{deal.invoice_date}} |
| **Due date** | {{deal.due_date}} |
| **Payment terms** | {{deal.payment_terms}} |
| **Reference** | Contract `{{deal.contract_id}}` |

---

## Bill from

**{{entity.legal_name}}**
{{entity.address}}

EIN/Tax ID: {{entity.tax_id}}

## Bill to

**{{deal.bill_to_name}}**
{{deal.bill_to_address}}

Attn: {{deal.bill_to_attention}}

---

## Line items

| Description | Amount |
|---|---|
| {{deal.line_item_1}} | ${{deal.line_item_1_amount}} |
| {{deal.line_item_2}} | ${{deal.line_item_2_amount}} |
| {{deal.line_item_3}} | ${{deal.line_item_3_amount}} |

| | |
|---|---|
| Subtotal | ${{deal.subtotal}} |
| Tax | ${{deal.tax_amount}} |
| **Total due** | **${{deal.total_due}}** |

---

## Payment instructions

{{deal.payment_instructions}}

---

## Notes

{{deal.notes}}

---

*Questions about this invoice: {{tenant.signatory_email}}*
