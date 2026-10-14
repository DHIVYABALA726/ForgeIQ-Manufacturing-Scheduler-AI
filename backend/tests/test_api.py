from __future__ import annotations

BASE = "2032-05-11T08:00:00Z"


def create_fixture(client):
    job = {"id": "J-1", "name": "Bracket", "product_name": "Mount", "quantity": 4, "priority": "High", "release_at": BASE, "due_at": "2032-05-11T10:00:00Z", "notes": ""}
    machine = {"id": "M-1", "name": "Mill", "machine_type": "CNC", "available_from": BASE, "available_until": None, "is_available": True, "setup_time_minutes": 0}
    operation = {"id": "OP-1", "job_id": "J-1", "name": "Cut", "sequence": 1, "eligible_machine_ids": ["M-1"], "processing_time_minutes": 35, "setup_time_minutes": 3, "predecessor_id": None}
    return job, machine, operation


def test_empty_crud_duplicate_and_operation_validation(client):
    assert client.get('/api/v1/jobs').json()['items'] == []
    job, machine, operation = create_fixture(client)
    assert client.post('/api/v1/jobs', json=job).status_code == 201
    assert client.get('/api/v1/jobs/J-1').json()['id'] == 'J-1'
    assert client.post('/api/v1/jobs', json=job).status_code == 409
    assert client.post('/api/v1/jobs', json={**job, 'id': 'J-2', 'quantity': 0}).status_code == 422
    assert client.post('/api/v1/jobs', json={**job, 'id': 'J-TZ', 'release_at': '2032-05-11T16:00:00+05:00', 'due_at': '2032-05-11T10:00:00Z'}).status_code == 422
    assert client.post('/api/v1/machines', json=machine).status_code == 201
    operation['job_id'] = 'MISSING'
    assert client.post('/api/v1/operations', json=operation).status_code == 422
    operation['job_id'] = 'J-1'; operation['eligible_machine_ids'] = ['UNKNOWN']
    assert client.post('/api/v1/operations', json=operation).status_code == 422
    operation['eligible_machine_ids'] = ['M-1']
    assert client.post('/api/v1/operations', json=operation).status_code == 201
    assert client.get('/api/v1/operations').json()['items'][0]['eligible_machine_ids'] == ['M-1']
    assert client.delete('/api/v1/machines/M-1').status_code == 409
    assert client.put('/api/v1/jobs/J-1', json={**job, 'name': 'Bracket revised'}).json()['name'] == 'Bracket revised'
    assert client.delete('/api/v1/jobs/J-1').status_code == 204
    assert client.get('/api/v1/operations').json()['items'] == []


def test_schedule_is_persisted_and_gantt_matches_backend_operations(client):
    job, machine, operation = create_fixture(client)
    assert client.post('/api/v1/jobs', json=job).status_code == 201
    assert client.post('/api/v1/machines', json=machine).status_code == 201
    assert client.post('/api/v1/operations', json=operation).status_code == 201
    response = client.post('/api/v1/schedules/generate', json={"scenario": "parallel_machine", "algorithms": ["FCFS", "SPT"], "objective": "makespan", "secondary_objectives": [], "hard_due_dates": False})
    assert response.status_code == 201, response.text
    run = response.json()
    assert run['hard_due_dates'] is False
    assert run['input_snapshot']['hard_due_dates'] is False
    assert run['recommended_algorithm_name'] in ['FCFS', 'SPT']
    assert run['recommendation_details']['scope'].startswith('Best among')
    for result in run['results']:
        assert result['feasible']
        assert len(result['scheduled_operations']) == 1
        assert result['scheduled_operations'][0]['operation_id'] == 'OP-1'
        assert result['objective_value'] == result['metrics']['makespan']
        assert result['constraint_violations'] == []
    run_id = run['id']
    comparison = client.get(f'/api/v1/schedules/{run_id}/comparison').json()
    assert comparison['hard_due_dates'] is False
    assert {item['algorithm_name'] for item in comparison['algorithms']} == {'FCFS', 'SPT'}
    gantt = client.get(f'/api/v1/schedules/{run_id}/gantt?algorithm_name=SPT').json()
    assert gantt['scheduled_operations'] == next(x for x in run['results'] if x['algorithm_name'] == 'SPT')['scheduled_operations']
    recommendation = client.get(f'/api/v1/schedules/{run_id}/recommendation').json()
    assert recommendation['recommended_algorithm_name'] == run['recommended_algorithm_name']
    assert recommendation['objective'] == 'makespan'
    assert recommendation['hard_due_dates'] is False
    assert client.post(f'/api/v1/schedules/{run_id}/select', json={'algorithm_name': 'SPT'}).status_code == 200
    assert client.get(f'/api/v1/schedules/{run_id}').json()['selected_algorithm_name'] == 'SPT'
    updated = client.put('/api/v1/machines/M-1', json={**machine, 'setup_time_minutes': 4})
    assert updated.status_code == 200
    assert client.get(f'/api/v1/schedules/{run_id}').json()['is_stale'] is True
    assert client.get('/api/v1/schedules').json()['items'][0]['is_stale'] is True


def test_hard_due_date_violation_is_infeasible_masked_and_has_no_gantt(client):
    job, machine, operation = create_fixture(client)
    job['due_at'] = '2032-05-11T08:10:00Z'
    for route, item in [('/api/v1/jobs', job), ('/api/v1/machines', machine), ('/api/v1/operations', operation)]:
        assert client.post(route, json=item).status_code == 201
    response = client.post('/api/v1/schedules/generate', json={"scenario": "parallel_machine", "algorithms": ["FCFS"], "objective": "makespan", "hard_due_dates": True})
    assert response.status_code == 201
    run = response.json()
    assert run['hard_due_dates'] is True
    assert run['input_snapshot']['hard_due_dates'] is True
    assert run['recommended_algorithm_name'] is None
    assert run['results'][0]['feasible'] is False
    assert run['results'][0]['metrics'] == {}
    assert run['results'][0]['scheduled_operations'] == []
    assert 'Hard due-date constraint violated' in run['results'][0]['error_message']
    assert run['results'][0]['objective_value'] is None
    assert run['results'][0]['constraint_violations'] == [run['results'][0]['error_message']]
    persisted = client.get(f"/api/v1/schedules/{run['id']}").json()
    assert persisted['hard_due_dates'] is True and persisted['input_snapshot']['hard_due_dates'] is True
    comparison = client.get(f"/api/v1/schedules/{run['id']}/comparison").json()
    assert comparison['hard_due_dates'] is True and comparison['algorithms'][0]['metrics'] == {}
    recommendation = client.get(f"/api/v1/schedules/{run['id']}/recommendation").json()
    assert recommendation['hard_due_dates'] is True
    gantt = client.get(f"/api/v1/schedules/{run['id']}/gantt?algorithm_name=FCFS")
    assert gantt.status_code == 422


def test_crud_cannot_forge_sample_marker_or_remove_manual_records(client):
    job, machine, operation = create_fixture(client)
    job['is_sample'] = machine['is_sample'] = operation['is_sample'] = True
    assert client.post('/api/v1/jobs', json=job).json()['is_sample'] is False
    assert client.post('/api/v1/machines', json=machine).json()['is_sample'] is False
    assert client.post('/api/v1/operations', json=operation).json()['is_sample'] is False
    assert client.put('/api/v1/jobs/J-1', json={**job, 'name': 'Manual bracket'}).json()['is_sample'] is False
    assert client.put('/api/v1/machines/M-1', json={**machine, 'name': 'Manual mill'}).json()['is_sample'] is False
    assert client.put('/api/v1/operations/OP-1', json={**operation, 'name': 'Manual cut'}).json()['is_sample'] is False
    assert client.delete('/api/v1/sample').status_code == 404
    assert len(client.get('/api/v1/jobs').json()['items']) == 1
    assert len(client.get('/api/v1/machines').json()['items']) == 1
    assert len(client.get('/api/v1/operations').json()['items']) == 1


def test_sample_data_is_explicitly_loaded_labelled_and_flowshop_ready(client):
    assert client.get('/api/v1/jobs').json()['items'] == []
    loaded = client.post('/api/v1/sample')
    assert loaded.status_code == 201
    assert all(item['is_sample'] for item in client.get('/api/v1/jobs').json()['items'])
    assert all(item['is_sample'] for item in client.get('/api/v1/operations').json()['items'])
    sample_job = client.get('/api/v1/jobs/J-201').json()
    assert client.put('/api/v1/jobs/J-201', json={**sample_job, 'is_sample': False}).json()['is_sample'] is True
    assert client.post('/api/v1/sample').status_code == 409
    run = client.post('/api/v1/schedules/generate', json={"scenario": "permutation_flow_shop", "algorithms": ["NEH"], "objective": "makespan"})
    assert run.status_code == 201, run.text
    assert run.json()['results'][0]['feasible'] is True
    assert len(run.json()['results'][0]['scheduled_operations']) == 9
    gantt = client.get(f"/api/v1/schedules/{run.json()['id']}/gantt?algorithm_name=NEH").json()
    assert gantt['scheduled_operations'] == run.json()['results'][0]['scheduled_operations']
    assert client.delete('/api/v1/sample').status_code == 200
    assert client.get('/api/v1/jobs').json()['items'] == []
    assert client.get('/api/v1/machines').json()['items'] == []
    assert client.get('/api/v1/operations').json()['items'] == []


def test_health_unsupported_scenario_and_meaningful_empty_schedule_error(client):
    assert client.get('/api/v1/health').json()['status'] == 'ok'
    response = client.post('/api/v1/schedules/generate', json={"scenario": "job_shop", "algorithms": ["FCFS"], "objective": "makespan"})
    assert response.status_code == 422
    assert 'job' in response.json()['detail'].lower()
    job, machine, operation = create_fixture(client)
    for route, item in [('/api/v1/jobs', job), ('/api/v1/machines', machine), ('/api/v1/operations', operation)]:
        assert client.post(route, json=item).status_code == 201
    unsupported = client.post('/api/v1/schedules/generate', json={"scenario": "permutation_flow_shop", "algorithms": ["FCFS"], "objective": "makespan"})
    assert unsupported.status_code == 422
