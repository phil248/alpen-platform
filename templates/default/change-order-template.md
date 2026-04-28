<!--
TEMPLATE: change-order-template
USE: in-engagement scope/schedule/fee adjustment under an executed SOW
APPLIES: tier 2 and tier 3 engagements
VOICE: precise; legally binding; no em/en dashes per universal rules
-->

# Change Order #{{deal.change_order_number}} to Statement of Work #{{deal.sow_number}}

**Reference SOW**: Statement of Work #{{deal.sow_number}} dated {{deal.sow_effective_date}} between **{{deal.contracting_entity}}** ("Service Provider") and **{{deal.client_name}}** ("Client").

**Change Order Effective Date**: {{deal.change_order_effective_date}}

This Change Order is governed by the SOW and the Master Services Agreement that the SOW incorporates. Capitalized terms not defined here have the meanings given in the SOW or MSA.

---

## 1. Description of change

{{deal.change_description}}

## 2. Reason for change

{{deal.change_reason}}

## 3. Scope delta

The following scope items are added, removed, or modified:

{{deal.scope_delta}}

## 4. Schedule delta

| Milestone | Original | Revised |
|---|---|---|
| {{deal.milestone_1_name}} | {{deal.milestone_1_original}} | {{deal.milestone_1_revised}} |
| {{deal.milestone_2_name}} | {{deal.milestone_2_original}} | {{deal.milestone_2_revised}} |
| Final delivery | {{deal.final_delivery_original}} | {{deal.final_delivery_revised}} |

Net schedule change: **{{deal.schedule_delta_days}} days**.

## 5. Fee delta

| Item | Amount |
|---|---|
| Original SOW fee | ${{deal.original_value}} |
| This change order | ${{deal.value_delta}} |
| **Revised SOW fee** | **${{deal.revised_value}}** |

Hours delta: {{deal.hours_delta}} hours.

Payment for this change order is invoiced per the SOW payment schedule, with the additional fee added to the next milestone trigger unless specified otherwise below:

{{deal.payment_terms}}

## 6. Assumptions and dependencies

The following assumptions underlie this Change Order. Material deviation triggers a further change order under SOW Section 8.

1. {{deal.assumption_1}}
2. {{deal.assumption_2}}

## 7. All other terms unchanged

All other terms and conditions of the SOW and MSA remain in full force and effect.

---

**IN WITNESS WHEREOF**, the Parties have executed this Change Order as of the Change Order Effective Date.

**{{deal.contracting_entity}}**

Signature: __________________________________________

Name: {{tenant.signatory_name}}

Title: {{tenant.signatory_title}}

Date: _______________________________________________

**{{deal.client_name}}**

Signature: __________________________________________

Name: {{deal.client_signatory_name}}

Title: {{deal.client_signatory_title}}

Date: _______________________________________________
