<!--
TEMPLATE: nda-template
USE: one-way Confidentiality Agreement (NDA / CDA)
APPLIES: pre-engagement information exchange; standalone or as a precursor to MSA/SOW
VOICE: legal register; precision over warmth; no em/en dashes per universal rules
NOTE: starting point, NOT legal advice. Have it reviewed by counsel before first use.

Roles:
  Disclosing Party - owns the Confidential Information being shared
  Receiving Party  - agrees to protect what it receives ("Contractor" in source)

The {{deal.disclosing_*}} variables describe whoever is sharing.
The {{deal.receiving_*}} variables describe whoever is protecting.

For the most common Alpen Platform use case (a prospective client shares data
with us during sales scoping):
  Disclosing Party = the client
  Receiving Party  = our entity (CCG or Alpen Tech)

For the inverse (we share methodology / IP with a partner):
  Disclosing Party = our entity
  Receiving Party  = the partner

bin/compose-nda.py --direction inbound (default) or --direction outbound
flips the assignment.

Source: adapted from the InnoSync AlpenTech CDA executed 2026-02-23,
parameterized with role-flexible {{deal.disclosing_*}} / {{deal.receiving_*}}
fields. Mutual NDAs (both parties as discloser and receiver) deferred to v0.2.
-->

# CONFIDENTIALITY AGREEMENT

{{deal.disclosing_legal_name}}, {{deal.disclosing_entity_descriptor}} having an address at {{deal.disclosing_address}} ("{{deal.disclosing_short_name}}"), and

{{deal.receiving_legal_name}}, having an address at {{deal.receiving_address}} ("Contractor")

wish to discuss potential project(s) described in Attachment A (the "Project"). In doing so, {{deal.disclosing_short_name}} may share Confidential Information (as defined in Section 1 below) with Contractor, or Contractor may obtain Confidential Information from others at the direction of {{deal.disclosing_short_name}}. In consideration of {{deal.disclosing_short_name}}'s agreement to share Confidential Information with the Contractor, Contractor agrees to protect the Confidential Information it receives using the reasonable measures described in this Agreement.

## 1. WHAT IS CONFIDENTIAL INFORMATION?

Contractor will treat as confidential any information described in Attachment A together with any confidential, proprietary, trade secret or other non-public information, materials, or samples that it obtains, sees, hears, reads, or otherwise learns in connection with the Project that relate to {{deal.disclosing_short_name}}, whether obtained from {{deal.disclosing_short_name}}, any Affiliates, or a third party at the direction of {{deal.disclosing_short_name}} ("Confidential Information" or "CI").

## 2. WHAT IS NOT CONFIDENTIAL INFORMATION?

Information is not CI if it: (a) is or becomes publicly known through no breach of this Agreement; (b) is known to Contractor prior to {{deal.disclosing_short_name}} sharing it, as documented by Contractor's business records; (c) is disclosed to Contractor by a third party having no confidentiality obligation to {{deal.disclosing_short_name}}, as documented by Contractor's or third party's business records; or (d) is independently developed by Contractor without using CI, as documented by Contractor's business records. {{deal.disclosing_short_name}} has no obligation to treat any information provided by Contractor as confidential under this Agreement.

## 3. WHEN MAY CONTRACTOR OBTAIN CONFIDENTIAL INFORMATION?

Contractor may obtain CI starting on the date listed on Attachment A as the "Beginning CI Sharing Date" and ending one year after that or at the end of the Project, whichever is later. {{deal.disclosing_short_name}} will share CI at its discretion and is not required to share any information under this Agreement. Contractor will not acquire any rights to CI.

## 4. HOW WILL CONTRACTOR PROTECT CONFIDENTIAL INFORMATION?

Contractor will act in good faith to protect the confidentiality of CI. This commitment means that: (a) Contractor will not disclose CI except as permitted by Sections 5 and 6 below or with {{deal.disclosing_short_name}}'s prior written approval; (b) Contractor will use CI only as needed in connection with the Project; and (c) Contractor will take all reasonable measures to guard against inadvertent disclosure of CI.

## 5. WHO MAY HAVE ACCESS TO CONFIDENTIAL INFORMATION?

Contractor will allow access to CI only to: (a) its employees and its Affiliates' employees who need access to the CI in order to perform the Project; (b) its lawyers, accountants and auditors; and (c) its agents and subcontractors who (i) need access to the CI to perform the Project, (ii) have been pre-approved by {{deal.disclosing_short_name}} to work on the Project, and (iii) have signed confidentiality agreements reasonably acceptable to {{deal.disclosing_short_name}}.

## 6. WHEN MAY CONTRACTOR DISCLOSE CONFIDENTIAL INFORMATION TO OTHERS?

If Contractor is required by law or by court or government order to disclose CI, Contractor must notify {{deal.disclosing_short_name}} as soon as possible (unless Contractor is legally prohibited from doing so) and may disclose such CI only to the limited extent required to comply with the law or order.

## 7. HOW LONG MUST CONTRACTOR PROTECT CONFIDENTIAL INFORMATION?

Contractor must protect CI until five years after the Beginning CI Sharing Date or, if the Project lasts more than one year, five years after the end of the Project. In addition, CI identified by {{deal.disclosing_short_name}} in writing as a trade secret and which meets legal requirements to be a trade secret shall be kept confidential forever, or at least as long as the CI remains a trade secret.

## 8. WHAT HAPPENS TO CONFIDENTIAL INFORMATION WHEN THE PROJECT ENDS?

If requested by {{deal.disclosing_short_name}}, Contractor will take all reasonable measures to remove CI from its files (including electronic) and delete, destroy, or return it at {{deal.disclosing_short_name}}'s option, taking into account what is reasonably practical under the circumstances. Contractor may keep one copy of documents containing CI secured in its legal files. The parties will consult in good faith to agree on any appropriate alternative procedures as needed.

## 9. HOW WILL THIS AGREEMENT BE INTERPRETED OR CHANGED?

The laws applying to contracts made at {{deal.disclosing_short_name}}'s location noted above will govern this Agreement, and disputes relating to this Agreement or its formation will be resolved in the courts having jurisdiction closest to {{deal.disclosing_short_name}}'s location noted above (except that injunctions may be sought in any appropriate jurisdiction to prevent actual or potential violations of this Agreement). In addition, the parties intend that this Agreement be interpreted in light of basic principles of good faith, common sense business practices, and the importance of the CI. This document contains the parties' entire agreement regarding CI in connection with the Project. Contractor will be in breach of this Agreement if it discloses CI to another person or entity that uses or discloses such CI (directly or indirectly through others) in breach of Contractor's obligations in this Agreement. To the extent {{deal.disclosing_short_name}} provides CI belonging to one or more of its Affiliates, or a third party, such entity or person is a third party beneficiary of this Agreement. However, no third party beneficiary's consent is required to change or terminate this Agreement. Any changes to this Agreement require another document signed by both parties.

---

Our authorized representatives execute this document by signing below. We may sign separate copies.

| {{deal.disclosing_legal_name}} | {{deal.receiving_legal_name}} |
|---|---|
| Signed: | Signed: |
| Print Name: {{deal.disclosing_signatory_name}} | Print Name: {{deal.receiving_signatory_name}} |
| Title: {{deal.disclosing_signatory_title}} | Title: {{deal.receiving_signatory_title}} |
| Date: | Date: |

---

## ATTACHMENT A

**Project Description:**

{{deal.project_description}}

**Information expected to be shared includes, but is not limited to:**

{{deal.information_categories}}

**Beginning CI Sharing Date:** {{deal.beginning_ci_sharing_date}}
