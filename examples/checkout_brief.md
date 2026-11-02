# Feature: Checkout Redesign

## Overview

Cart abandonment at checkout is 68%. This brief covers the stories needed to
ship a faster, guest-friendly checkout for Q1.

## Non-goals

- Changing payment providers
- Loyalty points redemption

## Story: Guest checkout
Priority: High
Labels: checkout, mvp
Story Points: 5
Component: Web

As a **first-time shopper**, I want to check out without creating an account,
so that I can complete my purchase quickly.

Guest orders must still receive a confirmation email.

### Acceptance Criteria
- Given I am not signed in, when I open checkout, then I see a "Continue as guest" option
- Given I check out as a guest, when the order is placed,
  then a confirmation email is sent to the address I entered
- Guest checkout does not require a password field

## Story: Saved payment methods
**Priority:** P2
**Labels:** payments

As a returning customer, I want to reuse a saved card so that I don't have to
re-enter my details every time.

Acceptance Criteria:
1. Saved cards show brand and last 4 digits only
2. I can delete a saved card from the checkout page
3. CVV is always re-requested

## Story: Address autocomplete
Priority: nice to have

As a shopper, I want address suggestions while typing so that I make fewer
typos. See [design spec](https://example.com/spec).

### Acceptance Criteria
- [ ] Suggestions appear after 3 characters
- [ ] Selecting a suggestion fills street, city, and postcode
- [ ] Works with keyboard only (`Tab`, `Enter`, arrow keys)
