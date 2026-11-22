-- FlightDeck pilot: hidden state layer (harness only; FlightDeck never reads this DB)
PRAGMA foreign_keys = ON;

CREATE TABLE clinicians (
  id   TEXT PRIMARY KEY,          -- 'C-1'
  name TEXT NOT NULL              -- 'Dr. Rao'
);

CREATE TABLE patients (
  id   TEXT PRIMARY KEY,          -- 'P-31'
  name TEXT NOT NULL              -- 'Asha N.' (synthetic)
);

CREATE TABLE appointments (
  id           TEXT PRIMARY KEY,  -- 'A-104'
  patient_id   TEXT NOT NULL REFERENCES patients(id),
  clinician_id TEXT NOT NULL REFERENCES clinicians(id),
  start        TEXT NOT NULL,     -- ISO 8601 with offset, e.g. 2026-12-15T16:00:00+05:30
  duration_min INTEGER NOT NULL,
  status       TEXT NOT NULL CHECK (status IN ('booked', 'cancelled')),
  updated_at   TEXT NOT NULL
);
-- Deliberately NO unique (clinician_id, start): the portal allows double-booking,
-- so FlightDeck's own pre-write check is what prevents it (fixture O1).

CREATE TABLE notifications (
  seq     INTEGER PRIMARY KEY AUTOINCREMENT,
  appt_id TEXT NOT NULL,
  kind    TEXT NOT NULL,          -- 'rescheduled'
  at      TEXT NOT NULL
);

-- Every write is logged, so the scorer can count writes exactly ("moved exactly once").
CREATE TABLE audit_log (
  seq     INTEGER PRIMARY KEY AUTOINCREMENT,
  op      TEXT NOT NULL,          -- insert | update | delete
  appt_id TEXT NOT NULL,
  before  TEXT,                   -- JSON or NULL
  after   TEXT,                   -- JSON or NULL
  at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);

CREATE TRIGGER appt_insert AFTER INSERT ON appointments BEGIN
  INSERT INTO audit_log (op, appt_id, before, after)
  VALUES ('insert', NEW.id, NULL,
          json_object('patient_id', NEW.patient_id, 'clinician_id', NEW.clinician_id,
                      'start', NEW.start, 'duration_min', NEW.duration_min, 'status', NEW.status));
END;

CREATE TRIGGER appt_update AFTER UPDATE ON appointments BEGIN
  INSERT INTO audit_log (op, appt_id, before, after)
  VALUES ('update', OLD.id,
          json_object('patient_id', OLD.patient_id, 'clinician_id', OLD.clinician_id,
                      'start', OLD.start, 'duration_min', OLD.duration_min, 'status', OLD.status),
          json_object('patient_id', NEW.patient_id, 'clinician_id', NEW.clinician_id,
                      'start', NEW.start, 'duration_min', NEW.duration_min, 'status', NEW.status));
END;

CREATE TRIGGER appt_delete AFTER DELETE ON appointments BEGIN
  INSERT INTO audit_log (op, appt_id, before, after)
  VALUES ('delete', OLD.id,
          json_object('patient_id', OLD.patient_id, 'clinician_id', OLD.clinician_id,
                      'start', OLD.start, 'duration_min', OLD.duration_min, 'status', OLD.status),
          NULL);
END;
