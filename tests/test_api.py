def register_and_login(client, email="client@example.com"):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "Client-test-password-123",
            "first_name": "Amina",
            "last_name": "Hassan",
            "phone": "+201000000000",
        },
    )
    assert response.status_code == 201, response.text
    token = client.post(
        "/api/v1/auth/token",
        data={"username": email, "password": "Client-test-password-123"},
    )
    assert token.status_code == 200, token.text
    return response.json(), {"Authorization": f"Bearer {token.json()['access_token']}"}


def test_client_registration_login_and_profile(api):
    client, _ = api
    profile, headers = register_and_login(client)
    assert profile["first_name"] == "Amina"
    assert profile["email"] == "client@example.com"
    current = client.get("/api/v1/clients/me", headers=headers)
    assert current.status_code == 200
    assert current.json()["id"] == profile["id"]
    updated = client.patch("/api/v1/clients/me", headers=headers, json={"first_name": "Amira"})
    assert updated.status_code == 200
    assert updated.json()["first_name"] == "Amira"
    email_update = client.patch(
        "/api/v1/clients/me", headers=headers, json={"email": "AMINA@example.com"}
    )
    assert email_update.status_code == 200
    assert email_update.json()["email"] == "amina@example.com"
    duplicate_email, _ = register_and_login(client, email="other@example.com")
    conflict = client.patch(
        "/api/v1/clients/me", headers=headers, json={"email": duplicate_email["email"]}
    )
    assert conflict.status_code == 409


def test_client_cannot_read_staff_data(api):
    client, _ = api
    _, headers = register_and_login(client)
    assert client.get("/api/v1/admin/employees", headers=headers).status_code == 403
    assert (
        client.post(
            "/api/v1/admin/categories", headers=headers, json={"name": "Computers"}
        ).status_code
        == 403
    )


def test_cash_order_is_priced_from_catalog_and_idempotent(api):
    client, seed = api
    _, headers = register_and_login(client)
    payload = {
        "items": [{"product_id": str(seed["product_id"]), "quantity": 2}],
        "branch_id": str(seed["branch_id"]),
        "fulfillment_method": "store_pickup",
        "payment_method": "cash_on_delivery",
    }
    first = client.post(
        "/api/v1/orders", headers={**headers, "Idempotency-Key": "checkout-001"}, json=payload
    )
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["total_amount"] == "24000.00"
    assert body["status"] == "confirmed"
    assert body["payment_status"] == "cod_due"
    replay = client.post(
        "/api/v1/orders", headers={**headers, "Idempotency-Key": "checkout-001"}, json=payload
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == body["id"]
    mismatch = client.post(
        "/api/v1/orders",
        headers={**headers, "Idempotency-Key": "checkout-001"},
        json={**payload, "items": [{"product_id": str(seed["product_id"]), "quantity": 1}]},
    )
    assert mismatch.status_code == 409
    assert (
        client.get("/api/v1/admin/inventory", headers=admin_headers(client)).json()[0]["quantity"]
        == 3
    )


def admin_headers(client):
    response = client.post(
        "/api/v1/auth/token",
        data={"username": "admin@infinity.test", "password": "Local-test-admin-password-123"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_insufficient_stock_does_not_create_an_order(api):
    client, seed = api
    _, headers = register_and_login(client)
    response = client.post(
        "/api/v1/orders",
        headers=headers,
        json={
            "items": [{"product_id": str(seed["product_id"]), "quantity": 6}],
            "branch_id": str(seed["branch_id"]),
            "fulfillment_method": "store_pickup",
            "payment_method": "cash_on_delivery",
        },
    )
    assert response.status_code == 409
    assert client.get("/api/v1/orders", headers=headers).json() == []


def test_mock_card_flow_uses_display_metadata_and_is_confirmed_by_callback(api):
    client, seed = api
    _, headers = register_and_login(client)
    unsafe_input = client.post(
        "/api/v1/clients/me/payment-methods/demo",
        headers=headers,
        json={
            "brand": "Visa",
            "last_four": "4242",
            "expiry_month": 12,
            "expiry_year": 2030,
            "card_number": "4111111111111111",
            "security_code": "123",
        },
    )
    assert unsafe_input.status_code == 422
    method = client.post(
        "/api/v1/clients/me/payment-methods/demo",
        headers=headers,
        json={"brand": "Visa", "last_four": "4242", "expiry_month": 12, "expiry_year": 2030},
    )
    assert method.status_code == 201, method.text
    assert method.json()["last_four"] == "4242"
    assert "token" not in method.text.lower()
    order = client.post(
        "/api/v1/orders",
        headers=headers,
        json={
            "items": [{"product_id": str(seed["product_id"]), "quantity": 1}],
            "branch_id": str(seed["branch_id"]),
            "fulfillment_method": "home_delivery",
            "payment_method": "card",
            "payment_method_id": method.json()["id"],
            "shipping_address": {
                "recipient_name": "Amina Hassan",
                "phone": "+201000000000",
                "line1": "1 Test Street",
                "city": "Cairo",
                "region": "Cairo",
            },
        },
    )
    assert order.status_code == 201, order.text
    assert order.json()["status"] == "payment_pending"
    payment_id = order.json()["payment"]["id"]
    completed = client.post(f"/api/v1/payments/mock/{payment_id}/complete", headers=headers)
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "confirmed"
    assert completed.json()["payment_status"] == "paid"


def test_home_delivery_requires_address(api):
    client, seed = api
    _, headers = register_and_login(client)
    response = client.post(
        "/api/v1/orders",
        headers=headers,
        json={
            "items": [{"product_id": str(seed["product_id"]), "quantity": 1}],
            "branch_id": str(seed["branch_id"]),
            "fulfillment_method": "home_delivery",
            "payment_method": "cash_on_delivery",
        },
    )
    assert response.status_code == 422


def test_saved_card_default_moves_and_is_reassigned_when_removed(api):
    client, _ = api
    _, headers = register_and_login(client)
    fake_card = {"brand": "Visa", "last_four": "4242", "expiry_month": 12, "expiry_year": 2030}
    first = client.post("/api/v1/clients/me/payment-methods/demo", headers=headers, json=fake_card)
    second = client.post(
        "/api/v1/clients/me/payment-methods/demo",
        headers=headers,
        json={**fake_card, "last_four": "1111"},
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["is_default"] is True
    assert second.json()["is_default"] is False

    selected = client.put(
        f"/api/v1/clients/me/payment-methods/{second.json()['id']}/default",
        headers=headers,
    )
    assert selected.status_code == 200
    methods = client.get("/api/v1/clients/me/payment-methods", headers=headers).json()
    assert [method["id"] for method in methods if method["is_default"]] == [second.json()["id"]]

    deleted = client.delete(
        f"/api/v1/clients/me/payment-methods/{second.json()['id']}", headers=headers
    )
    assert deleted.status_code == 204
    remaining = client.get("/api/v1/clients/me/payment-methods", headers=headers).json()
    assert len(remaining) == 1
    assert remaining[0]["id"] == first.json()["id"]
    assert remaining[0]["is_default"] is True


def test_order_uses_only_the_clients_saved_address_snapshot(api):
    client, seed = api
    _, headers = register_and_login(client)
    address = client.post(
        "/api/v1/clients/me/addresses",
        headers=headers,
        json={
            "recipient_name": "Amina Hassan",
            "phone": "+201000000000",
            "line1": "1 Test Street",
            "city": "Cairo",
            "region": "Cairo",
        },
    )
    assert address.status_code == 201
    assert address.json()["is_default"] is True
    order = client.post(
        "/api/v1/orders",
        headers=headers,
        json={
            "items": [{"product_id": str(seed["product_id"]), "quantity": 1}],
            "branch_id": str(seed["branch_id"]),
            "fulfillment_method": "home_delivery",
            "payment_method": "cash_on_delivery",
            "shipping_address_id": address.json()["id"],
        },
    )
    assert order.status_code == 201, order.text
    assert order.json()["shipping_address"]["line1"] == "1 Test Street"

    changed = client.patch(
        f"/api/v1/clients/me/addresses/{address.json()['id']}",
        headers=headers,
        json={"line1": "2 New Street"},
    )
    assert changed.status_code == 200
    refreshed_order = client.get(f"/api/v1/orders/{order.json()['id']}", headers=headers)
    assert refreshed_order.json()["shipping_address"]["line1"] == "1 Test Street"

    _, other_headers = register_and_login(client, "other-client@example.com")
    forbidden = client.post(
        "/api/v1/orders",
        headers=other_headers,
        json={
            "items": [{"product_id": str(seed["product_id"]), "quantity": 1}],
            "branch_id": str(seed["branch_id"]),
            "fulfillment_method": "home_delivery",
            "payment_method": "cash_on_delivery",
            "shipping_address_id": address.json()["id"],
        },
    )
    assert forbidden.status_code == 404


def test_staff_cannot_use_fulfillment_status_for_the_wrong_delivery_type(api):
    client, seed = api
    _, delivery_headers = register_and_login(client)
    delivery = client.post(
        "/api/v1/orders",
        headers=delivery_headers,
        json={
            "items": [{"product_id": str(seed["product_id"]), "quantity": 1}],
            "branch_id": str(seed["branch_id"]),
            "fulfillment_method": "home_delivery",
            "payment_method": "cash_on_delivery",
            "shipping_address": {
                "recipient_name": "Amina Hassan",
                "phone": "+201000000000",
                "line1": "1 Test Street",
                "city": "Cairo",
                "region": "Cairo",
            },
        },
    )
    assert delivery.status_code == 201
    staff = admin_headers(client)
    processing = client.patch(
        f"/api/v1/admin/orders/{delivery.json()['id']}/status",
        headers=staff,
        json={"status": "processing"},
    )
    assert processing.status_code == 200
    wrong_delivery_status = client.patch(
        f"/api/v1/admin/orders/{delivery.json()['id']}/status",
        headers=staff,
        json={"status": "ready_for_pickup"},
    )
    assert wrong_delivery_status.status_code == 409
