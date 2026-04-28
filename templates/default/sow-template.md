<!--
TEMPLATE: sow-template
USE: per-engagement statement of work, executed under an MSA
APPLIES: tier 2 and tier 3; tier 1 uses a simpler service order
VOICE: precise; legally binding; no em/en dashes per universal rules
-->

# Statement of Work #{{deal.sow_number}}

**Reference Master Services Agreement** between **{{deal.contracting_entity}}** ("Service Provider") and **{{deal.client_name}}** ("Client"), dated {{deal.msa_date}} ("MSA"). This Statement of Work ("SOW") is governed by and incorporated into the MSA.

**SOW Effective Date:** {{deal.sow_effective_date}}
**SOW Termination Date:** {{deal.sow_end_date}}
**Total fees under this SOW:** ${{deal.value}}

---

## 1. Services

Service Provider will deliver the following Services:

{{deal.services_summary}}

## 2. Deliverables

| # | Deliverable | Acceptance criteria | Due |
|---|---|---|---|
| 1 | {{deal.deliverable_1}} | {{deal.deliverable_1_criteria}} | {{deal.deliverable_1_due}} |
| 2 | {{deal.deliverable_2}} | {{deal.deliverable_2_criteria}} | {{deal.deliverable_2_due}} |
| 3 | {{deal.deliverable_3}} | {{deal.deliverable_3_criteria}} | {{deal.deliverable_3_due}} |

Acceptance: Client has 10 business days from delivery of each Deliverable to accept or to provide written notice of specific deficiencies. Silence beyond 10 business days constitutes acceptance.

## 3. Schedule

| Milestone | Target date | Owner |
|---|---|---|
| Kickoff | {{deal.kickoff_date}} | Service Provider |
| Discovery complete | {{deal.discovery_end}} | Service Provider |
| Mid-sprint demo | {{deal.midpoint_demo}} | Service Provider |
| Final delivery | {{deal.final_delivery}} | Service Provider |
| Acceptance | {{deal.acceptance_target}} | Client |

## 4. Fees and payment schedule

Total: **${{deal.value}}** (excluding travel and out-of-pocket expenses, billed at actual cost).

| Milestone | Amount | Trigger |
|---|---|---|
| Kickoff | ${{deal.payment_kickoff}} | Signature of this SOW |
| Mid-sprint demo accepted | ${{deal.payment_midpoint}} | Demo accepted by Client per Section 2 |
| Final acceptance | ${{deal.payment_final}} | Final Deliverables accepted per Section 2 |

Invoices are payable within 30 days of receipt per the MSA.

## 5. Service Provider team

| Name | Role | Allocation |
|---|---|---|
| {{tenant.principal_name}} | {{deal.principal_role}} | {{deal.principal_allocation}} |
| {{tenant.partner_name}} | {{deal.partner_role}} | {{deal.partner_allocation}} |
| {{deal.contributor_3_name}} | {{deal.contributor_3_role}} | {{deal.contributor_3_allocation}} |

## 6. Client team and obligations

Client will provide:

- A primary point of contact: {{deal.client_poc_name}}, {{deal.client_poc_title}}, {{deal.client_poc_email}}
- An executive sponsor: {{deal.client_sponsor_name}}, {{deal.client_sponsor_title}}
- Access to {{deal.access_systems}} within 5 business days of signature
- Stakeholder availability for {{deal.stakeholder_session_count}} working sessions per week
- Decision authority for {{deal.client_decision_areas}}, with named delegate {{deal.client_delegate_name}}

## 7. Assumptions and dependencies

The following assumptions underlie this SOW. Material deviation triggers a change-order discussion under Section 8.

1. {{deal.assumption_1}}
2. {{deal.assumption_2}}
3. {{deal.assumption_3}}

Dependencies on Client:

1. {{deal.dependency_1}}
2. {{deal.dependency_2}}

## 8. Change orders

Any change to scope, schedule, deliverables, or fees requires a written change order signed by both Parties. Service Provider will produce a change-order draft within 5 business days of a written request and will continue work on the unchanged scope while the change order is being negotiated.

## 9. Out of scope

The following are explicitly out of scope for this SOW:

- {{deal.out_of_scope_1}}
- {{deal.out_of_scope_2}}
- {{deal.out_of_scope_3}}

These items can be addressed under a separate SOW.

---

**IN WITNESS WHEREOF**, the Parties have executed this Statement of Work as of the SOW Effective Date.

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
