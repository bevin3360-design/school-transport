# Pilot runbook — one school, two weeks

Goal: get one real school running one real route, prove the loop
(admin → driver → parent), then convert the trial into a paid plan.

- Site: https://mytransport.onrender.com (landing), `/register`, `/login`
- Support number: +254 753 538 323 (WhatsApp)
- Trial: 30 days automatic at registration. After it lapses, the admin can still sign in
  but only reaches `/payment`; drivers, parents and teachers are refused at login.
- Plans: Basic KES 500/mo (4 routes, 10 teachers) · Standard KES 1,500/mo (8 routes, 20) ·
  Premium KES 3,000/mo (unlimited). Payment is M-Pesa to 0753538323, then the school
  submits the M-Pesa code on `/payment`; the operator verifies it in the super panel.

## Before the visit

1. Open https://mytransport.onrender.com 5 minutes before the meeting — the free Render
   service sleeps after ~15 min idle and the first load takes ~35–50 s.
2. Confirm `/register` and `/login` load (they do after the warm-up).
3. Collect from the school in advance:
   - School full name, county, school phone/email
   - Short school code, 4–8 characters, e.g. `GFA001` (everyone types it at login)
   - Route names (morning and evening), e.g. `Kileleshwa – Morning`
   - Driver name + phone, one per route
   - 3–5 parents: name, phone, child name, class, and which route

## Onboarding (about 15 minutes, do it together)

1. **Register the school** at `/register`. The admin username and password are the
   school's choice: 8–128 characters, at least one letter and one number, not the same as
   the username. The trial starts immediately.
2. **Sign in as admin** at `/login` (Admin tab) and land on the dashboard.
3. **Add routes** — Routes section, name + Morning/Evening. Basic allows 4 active routes.
4. **Add drivers** — each needs name, phone, a password (same 8+/letter+number rule) and a
   route. Write the password down for them; they log in with phone + password + school code.
5. **Add parents** — name, phone, password, child name, class, route. (Alternatively the
   parent self-registers from the login page with the school code, but then you must
   assign their route afterwards. For the pilot, add them yourself.)
6. **Parent phones** — tell each parent: open the site in Chrome, menu → *Add to Home
   screen*. Send them the parent message from `outreach-messages.md` with the school code
   and their password.

## Day-1 dry run (do this before the real morning run)

1. Driver opens the site on their own phone, logs in, taps **Start Tracking**, and allows
   location when Chrome asks.
2. Admin watches the dashboard map; the parent opens the parent page. The vehicle should
   appear within ~30 s and move as the phone moves.
3. Driver taps **Stop** afterwards. Repeat the next morning for real.

Notes to set expectations:
- The driver should keep the site open (screen on, phone charged) during the run —
  mobile browsers throttle location when the screen is off.
- Parent "I'm Ready for Pickup" alerts and driver notices are in-app only; there is no SMS.
- Traffic and first-load delay: the free Render service wakes slowly after idle.

## Weeks 1–2

- Day 3: WhatsApp check-in — did tracking work, did parents log in, any errors?
- Day 7: review the roster screen and location history with the admin.
- Day 25: renewal reminder; Basic is KES 500/month by M-Pesa.
- Log every issue in one WhatsApp thread to yourself so nothing is lost.

Pilot succeeds when: at least 10 tracked trips, at least 5 parents signed in, and no
wrong-school or wrong-child data. Then ask for the Basic payment.

## After each onboarding, verify (operator side)

- Admin dashboard loads and shows the new route/driver.
- `/api/admin/drivers` (signed in as admin) shows the driver with a fresh `last_update`
  after a test ping.
- Parent login returns 200 and the parent page shows the right child and route.
- Landing page still 200; nothing in the school data leaks across schools.

## Files in this folder

- `school-setup.html` — printable one-pager to leave with the school (open in a browser,
  Ctrl+P → save as PDF).
- `outreach-messages.md` — WhatsApp copy for first contact, follow-ups, parents, and
  renewal.
