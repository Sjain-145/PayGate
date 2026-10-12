import os
import time
import uuid

from locust import HttpUser, between, task


class PayGateUser(HttpUser):
    wait_time = between(0.05, 0.2)

    def on_start(self):
        self.api_key = os.environ["API_KEY"]
        self.customer_id = os.environ["CUSTOMER_ID"]
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @task(3)
    def create_payment(self):
        headers = {
            **self.headers,
            "Idempotency-Key": f"locust-{uuid.uuid4()}",
        }
        with self.client.post(
            "/payments",
            headers=headers,
            json={
                "customer_id": self.customer_id,
                "amount_minor": 1000,
                "currency": "INR",
            },
            catch_response=True,
            name="POST /payments",
        ) as resp:
            if resp.status_code != 201:
                resp.failure(f"status {resp.status_code}")
            else:
                self.last_payment_id = resp.json()["id"]

    @task(2)
    def get_payment(self):
        payment_id = getattr(self, "last_payment_id", None)
        if not payment_id:
            return
        self.client.get(
            f"/payments/{payment_id}",
            headers=self.headers,
            name="GET /payments/{id}",
        )

    @task(2)
    def list_payments(self):
        self.client.get("/payments?limit=20", headers=self.headers, name="GET /payments")
