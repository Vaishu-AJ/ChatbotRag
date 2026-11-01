---
type: DatabaseReference
title: Crew Passport Lookup
description: Read passport identity and passport-document fields from the local PostgreSQL database.
tags:
  - crew passport
  - passport document
aliases:
  - passport
  - passport document
  - passport documents
  - passport number
  - passport no
  - passport details
  - passport record
  - crew passport
  - crew passport document
  - crew passport details
  - passport of crew
  - crew code
  - crewcode
  - crew details
  - employee
  - employees
  - staff
  - staff members
  - workforce
status: stable
generated:
  by: machine:codex
  at: "2026-10-25T00:00:00Z"
sources:
  - id: crew-records
    resource: postgresql://localhost:5432/postgres#public.crew
    title: Public crew records
  - id: crew-passport-documents
    resource: postgresql://localhost:5432/postgres#public.crew_passport_document
    title: Public crew passport documents
database:
  nl_to_sql: true
  schema: public
  table: crew
  alias: base
  joins:
    - table: crew_passport_document
      alias: passport
      left: base.crew_code
      right: passport.crew_code
  search_columns:
    - base.surname
    - base.name
    - base.middle_name
    - base.crew_code
    - passport.passport_no
  record_presence_column: passport.crew_code
  record_label: passport document
  media_path_column: passport.document_path
  column_aliases:
    base.crew_code:
      - crew code
      - crewcode
      - crew ID
      - crew number
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
    base.country_code:
      - country code
      - nationality code
    base.rank_code:
      - rank
      - rank code
    passport.passport_no:
      - passport number
      - passport no
      - passport ID
      - travel document number
    passport.issue_date:
      - passport issue date
      - issue date
      - date of issue
    passport.issue_place:
      - passport issue place
      - issue place
      - place of issue
    passport.expiry_date:
      - passport expiry date
      - expiry date
      - expiration date
      - valid until
    passport.document_name:
      - passport document
      - passport file
      - passport document name
    passport.approved_status:
      - passport approval status
      - approval status
      - approved
  return_columns:
    - base.crew_code
    - base.surname
    - base.name
    - base.middle_name
    - base.birth_date
    - base.country_code
    - base.rank_code
    - passport.passport_no
    - passport.issue_date
    - passport.issue_place
    - passport.expiry_date
    - passport.document_name
    - passport.approved_status
  ignored_terms:
    - crew
    - passport
    - document
    - travel
  limit: 20
---

Look up passport documents by a crew member's name, crew code, or passport number. Use only the
passport document records linked to the matched crew row. Return only the fields listed in the
database mapping. Do not infer passport ownership from uploaded certificate or license documents.
Report passport numbers, document names, issue and expiry dates, issue place, country code, and
approval status exactly as stored. Report a missing link clearly rather than using documents belonging
to another crew member.
