import logging

from typing import Any, Dict, List

from amundsen_common.models.dashboard import DashboardSummary, DashboardSummarySchema
from amundsen_common.models.popular_table import PopularTable, PopularTableSchema
from amundsen_common.models.table import Table, TableSchema
from amundsen_application.models.user import load_user, dump_user
from flask import current_app as app
import re


def marshall_table_partial(table_dict: Dict) -> Dict:
    """
    Forms a short version of a table Dict, with selected fields and an added 'key'
    :param table: Dict of partial table object
    :return: partial table Dict

    TODO - Unify data format returned by search and metadata.
    """
    schema = PopularTableSchema(strict=True)
    # TODO: consider migrating to validate() instead of roundtripping
    table: PopularTable = schema.load(table_dict).data
    results = schema.dump(table).data
    # TODO: fix popular tables to provide these? remove if we're not using them?
    # TODO: Add the 'key' or 'id' to the base PopularTableSchema
    results['key'] = f'{table.database}://{table.cluster}.{table.schema}/{ table.name}'
    results['last_updated_timestamp'] = None
    results['type'] = 'table'

    return results


def marshall_table_full(table_dict: Dict) -> Dict:
    """
    Forms the full version of a table Dict, with additional and sanitized fields
    :param table: Table Dict from metadata service
    :return: Table Dict with sanitized fields
    """

    schema = TableSchema(strict=True)
    # TODO: consider migrating to validate() instead of roundtripping
    table: Table = schema.load(table_dict).data
    results: Dict[str, Any] = schema.dump(table).data

    # Check if schecma is uneditable
    is_editable_schema = results['schema'] not in app.config['UNEDITABLE_SCHEMAS']

    # Check if Table is uneditable
    table_id = results['schema']+"."+results['name']
    is_editable_table = True
    match = re.match(app.config['UNEDITABLE_TABLES_REGEX'], table_id)
    if match:
        is_editable_table = False

    is_editable = is_editable_schema and is_editable_table
    print("***IS_EDITABLE***",is_editable)
    results['is_editable'] = is_editable

    # TODO - Cleanup https://github.com/lyft/amundsen/issues/296
    #  This code will try to supplement some missing data since the data here is incomplete.
    #  Once the metadata service response provides complete user objects we can remove this.
    results['owners'] = [_map_user_object_to_schema(owner) for owner in results['owners']]
    readers = results['table_readers']
    for reader_object in readers:
        reader_object['user'] = _map_user_object_to_schema(reader_object['user'])

    # If order is provided, we sort the column based on the pre-defined order
    if app.config['COLUMN_STAT_ORDER']:
        columns = results['columns']
        for col in columns:
            # the stat_type isn't defined in COLUMN_STAT_ORDER, we just use the max index for sorting
            col['stats'].sort(key=lambda x: app.config['COLUMN_STAT_ORDER'].
                              get(x['stat_type'], len(app.config['COLUMN_STAT_ORDER'])))
            col['is_editable'] = is_editable

    # TODO: Add the 'key' or 'id' to the base TableSchema
    results['key'] = f'{table.database}://{table.cluster}.{table.schema}/{ table.name}'
    # Temp code to make 'partition_key' and 'partition_value' part of the table
    results['partition'] = _get_partition_data(results['watermarks'])

    # We follow same style as column stat order for arranging the programmatic descriptions
    prog_descriptions = results['programmatic_descriptions']
    if prog_descriptions:
        _update_prog_descriptions(prog_descriptions)

    return results


def marshall_dashboard_partial(dashboard_dict: Dict) -> Dict:
    """
    Forms a short version of dashboard metadata, with selected fields and an added 'key'
    and 'type'
    :param dashboard_dict: Dict of partial dashboard metadata
    :return: partial dashboard Dict
    """
    schema = DashboardSummarySchema(strict=True)
    dashboard: DashboardSummary = schema.load(dashboard_dict).data
    results = schema.dump(dashboard).data
    results['type'] = 'dashboard'
    # TODO: Bookmark logic relies on key, opting to add this here to avoid messy logic in
    # React app and we have to clean up later.
    results['key'] = results.get('uri', '')
    return results


def marshall_dashboard_full(dashboard_dict: Dict) -> Dict:
    """
    Cleanup some fields in the dashboard response
    :param dashboard_dict: Dashboard response from metadata service.
    :return: Dashboard dictionary with sanitized fields, particularly the tables and owners.
    """
    # TODO - Cleanup https://github.com/lyft/amundsen/issues/296
    #  This code will try to supplement some missing data since the data here is incomplete.
    #  Once the metadata service response provides complete user objects we can remove this.
    dashboard_dict['owners'] = [_map_user_object_to_schema(owner) for owner in dashboard_dict['owners']]
    dashboard_dict['tables'] = [marshall_table_partial(table) for table in dashboard_dict['tables']]
    return dashboard_dict


def _update_prog_descriptions(prog_descriptions: List) -> None:
    # We want to make sure there is a display title that is just source
    for desc in prog_descriptions:
        source = desc.get('source')
        if not source:
            logging.warning("no source found in: " + str(desc))
    prog_display_config = app.config['PROGRAMMATIC_DISPLAY']
    if prog_display_config and prog_descriptions:
        # If config is defined for programmatic disply we look to see what configuration is being used
        prog_descriptions.sort(key=lambda x: _sort_prog_descriptions(prog_display_config, x))


def _sort_prog_descriptions(base_config: Dict, prog_description: Dict) -> int:
    default_order = len(base_config)
    prog_description_source = prog_description.get('source')
    config_dict = base_config.get(prog_description_source)
    if config_dict:
        return config_dict.get('display_order', default_order)
    return default_order


def _map_user_object_to_schema(u: Dict) -> Dict:
    return dump_user(load_user(u))


def _get_partition_data(watermarks: Dict) -> Dict:
    if watermarks:
        high_watermark = next(filter(lambda x: x['watermark_type'] == 'high_watermark', watermarks))
        if high_watermark:
            return {
                'is_partitioned': True,
                'key': high_watermark['partition_key'],
                'value': high_watermark['partition_value']
            }
    return {
        'is_partitioned': False
    }
