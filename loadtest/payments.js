import http from "k6/http";
import { check, sleep } from "k6";
import { Rate } from "k6/metrics";

const errorRate = new Rate("errors");
const BASE = __ENV.BASE_URL || "http://localhost:8000";
const API_KEY = __ENV.API_KEY;
const CUSTOMER_ID = __ENV.CUSTOMER_ID;

export const options = {
  vus: 10,
  duration: "30s",
  thresholds: {
    http_req_failed: ["rate<0.05"],
    http_req_duration: ["p(95)<1500"],
  },
};

function headers(idempotencyKey) {
  const h = {
    Authorization: `Bearer ${API_KEY}`,
    "Content-Type": "application/json",
  };
  if (idempotencyKey) h["Idempotency-Key"] = idempotencyKey;
  return h;
}

export default function () {
  const key = `k6-${__VU}-${__ITER}-${Date.now()}`;
  const create = http.post(
    `${BASE}/payments`,
    JSON.stringify({
      customer_id: CUSTOMER_ID,
      amount_minor: 1000 + (__ITER % 500),
      currency: "INR",
      description: "k6 load",
    }),
    { headers: headers(key) }
  );
  const okCreate = check(create, { "create 201": (r) => r.status === 201 });
  errorRate.add(!okCreate);

  if (create.status === 201) {
    const id = create.json("id");
    const get = http.get(`${BASE}/payments/${id}`, { headers: headers() });
    errorRate.add(!check(get, { "get 200": (r) => r.status === 200 }));
  }

  const list = http.get(`${BASE}/payments?limit=20`, { headers: headers() });
  errorRate.add(!check(list, { "list 200": (r) => r.status === 200 }));
  sleep(0.1);
}
