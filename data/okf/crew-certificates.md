---
type: DatabaseReference
title: Crew Certificate Lookup
description: Read crew identity and license-document fields from the local PostgreSQL database.
tags:
  - crew certificate
  - seafarer license
aliases:
  - certificate
  - certificates
  - certificate details
  - crew certificate
  - crew certificates
  - crewcode
  - crew code
  - crew id
  - crew number
  - crew lookup
  - crew records
  - crew member
  - crew members
  - employee
  - employees
  - staff
  - staff members
  - workforce
  - who works here
  - employee list
  - show all employees
  - list all staff members
  - display the employee list
  - payroll
  - salary
  - bank details
  - bank account
  - address record
  - medical certificate
  - seaman book
  - crew details
  - crew personal details
  - date of birth
  - birth date
  - dob
  - birthdate
  - seafarer details
  - seafarer certificate
  - seafarer certificates
  - license details
  - licence details
status: stable
generated:
  by: machine:codex
  at: "2026-10-25T00:00:00Z"
sources:
  - id: crew-records
    resource: postgresql://localhost:5432/postgres#public.crew
    title: Public crew records
  - id: crew-license-documents
    resource: postgresql://localhost:5432/postgres#public.crew_license_document
    title: Public crew license documents
database:
  nl_to_sql: true
  schema: public
  table: crew
  alias: base
  joins:
    - table: crew_license_document
      alias: license
      left: base.crew_code
      right: license.crew_code
  search_columns:
    - base.surname
    - base.name
    - base.middle_name
    - base.crew_code
  record_presence_column: license.crew_code
  media_path_column: license.document_path
  column_aliases:
    base.crew_code:
      - crew code
      - crewcode
      - crew ID
      - crew number
      - crew identifier
    base.name:
      - first name
      - given name
      - forename
    base.surname:
      - family name
      - last name
    base.middle_name:
      - middle name
    base.birth_date:
      - date of birth
      - birth date
      - dob
      - birthdate
    base.rank_code:
      - rank
      - rank code
    license.document_name:
      - document name
      - certificate file
      - license file
    license.work_license_code:
      - work license code
      - license code
      - licence code
      - certificate code
      - certificate type
      - license type
    license.license_no:
      - certificate number
      - license number
      - licence number
      - certificate ID
      - license ID
    license.issue_date:
      - issue date
      - issued date
      - date of issue
    license.endorsement_date:
      - endorsement date
      - date endorsed
      - endorsed on
    license.expiry_date:
      - expiry date
      - expiration date
      - valid until
    license.issue_place:
      - issue place
      - place of issue
    license.country_code:
      - country code
      - nationality code
    license.approved_status:
      - approval status
      - approved
  return_columns:
    - base.crew_code
    - base.surname
    - base.name
    - base.middle_name
    - base.birth_date
    - base.rank_code
    - license.document_name
    - license.work_license_code
    - license.license_no
    - license.issue_date
    - license.endorsement_date
    - license.expiry_date
    - license.issue_place
    - license.country_code
    - license.approved_status
  ignored_terms:
    - license
    - licence
    - seafarer
    - crew
  limit: 20
---

Look up crew license and certificate records by the person's name or crew code. Column aliases
in the mapping are synonyms for the searchable and returned fields. The database records are in
`public.crew` and `public.crew_license_document`, joined by `crew_code`. Return only
the fields listed in the database mapping. Explain `work_license_code` and `rank_code` as stored
codes unless a corresponding human-readable lookup value is available. Include issue and expiry
dates as stored, and report approval status without treating it as proof of current validity.
