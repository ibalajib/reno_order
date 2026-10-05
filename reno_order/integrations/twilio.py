# Copyright (c) 2026, Balaji B and contributors
# For license information, please see license.txt

import time

import frappe
import requests
from frappe.utils import cint, now_datetime
from requests.auth import HTTPBasicAuth

TWILIO_URL_TEMPLATE = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
RETRYABLE_HTTP_STATUSES = {408, 429, 500, 502, 503, 504}
BACKOFF_BASE_SECONDS = 2


class TwilioConfigError(Exception):
	pass


def _load_settings():
	settings = frappe.get_cached_doc("Twilio Settings")

	if not settings.enabled:
		raise TwilioConfigError("Twilio integration is disabled in Twilio Settings.")

	sid = (settings.account_sid or "").strip()
	from_number = (settings.from_number or "").strip()
	token = settings.get_password("auth_token", raise_exception=False)

	if not sid or not token or not from_number:
		raise TwilioConfigError(
			"Twilio Settings is missing Account SID, Auth Token or From Number."
		)

	return {
		"sid": sid,
		"token": token,
		"from_number": from_number,
		"default_country_code": (settings.default_country_code or "").strip(),
		"timeout": cint(settings.request_timeout) or 10,
		"max_retries": cint(settings.max_retries) or 3,
		"trial_mode": bool(settings.trial_mode),
		"trial_body_override": (settings.trial_body_override or "").strip(),
	}


def normalize_number(raw, default_country_code=""):
	if not raw:
		return ""

	cleaned = "".join(ch for ch in str(raw) if ch.isdigit() or ch == "+")

	if cleaned.startswith("+"):
		return cleaned

	if default_country_code and cleaned:
		cc = default_country_code if default_country_code.startswith("+") else f"+{default_country_code}"
		return f"{cc}{cleaned.lstrip('0')}"

	return cleaned


def _create_log(reno_order, trigger_event, to_number, body):
	log = frappe.get_doc(
		{
			"doctype": "Twilio Message Log",
			"reno_order": reno_order,
			"trigger_event": trigger_event,
			"to_number": to_number,
			"body": body,
			"status": "Queued",
			"attempt": 0,
			"requested_on": now_datetime(),
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()
	return log


def _update_log(log_name, **fields):
	fields["completed_on"] = now_datetime()
	frappe.db.set_value("Twilio Message Log", log_name, fields)
	frappe.db.commit()


def send_sms(reno_order, to_number, body, trigger_event="manual"):
	try:
		cfg = _load_settings()
	except TwilioConfigError as exc:
		frappe.logger("reno_order.twilio").warning(str(exc))
		return {"ok": False, "reason": str(exc)}

	normalized_to = normalize_number(to_number, cfg["default_country_code"])
	if not normalized_to:
		return {"ok": False, "reason": "Destination number is empty."}

	log = _create_log(reno_order, trigger_event, normalized_to, body)

	outbound_body = body
	if cfg["trial_mode"] and cfg["trial_body_override"]:
		outbound_body = cfg["trial_body_override"]

	url = TWILIO_URL_TEMPLATE.format(sid=cfg["sid"])
	auth = HTTPBasicAuth(cfg["sid"], cfg["token"])
	payload = {
		"To": normalized_to,
		"From": cfg["from_number"],
		"Body": outbound_body,
	}

	last_error = None

	for attempt in range(1, cfg["max_retries"] + 1):
		try:
			response = requests.post(url, data=payload, auth=auth, timeout=cfg["timeout"])
		except requests.Timeout:
			last_error = {"code": "TIMEOUT", "message": f"Request timed out after {cfg['timeout']}s."}
			_sleep_before_retry(attempt)
			continue
		except requests.ConnectionError as exc:
			last_error = {"code": "CONNECTION", "message": str(exc)[:500]}
			_sleep_before_retry(attempt)
			continue
		except requests.RequestException as exc:
			last_error = {"code": "REQUEST", "message": str(exc)[:500]}
			break

		if response.status_code in (200, 201):
			data = response.json()
			_update_log(
				log.name,
				status="Sent",
				attempt=attempt,
				twilio_sid=data.get("sid"),
				error_code=None,
				error_message=None,
			)
			return {
				"ok": True,
				"log": log.name,
				"twilio_sid": data.get("sid"),
				"attempt": attempt,
			}

		error_payload = _parse_error(response)
		last_error = error_payload

		if response.status_code in RETRYABLE_HTTP_STATUSES:
			_sleep_before_retry(attempt)
			continue

		break

	_update_log(
		log.name,
		status="Failed",
		attempt=attempt,
		error_code=(last_error or {}).get("code"),
		error_message=(last_error or {}).get("message"),
	)
	frappe.log_error(
		title=f"Twilio send failed for {reno_order}",
		message=frappe.as_json(last_error or {}),
	)
	return {"ok": False, "log": log.name, "error": last_error}


def _parse_error(response):
	try:
		body = response.json()
		return {
			"code": str(body.get("code") or response.status_code),
			"message": body.get("message") or response.text[:500],
		}
	except ValueError:
		return {"code": str(response.status_code), "message": response.text[:500]}


def _sleep_before_retry(attempt):
	time.sleep(BACKOFF_BASE_SECONDS**attempt)
