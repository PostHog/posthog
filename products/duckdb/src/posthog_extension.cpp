#define DUCKDB_EXTENSION_MAIN

#include "posthog_extension.hpp"
#include "duckdb.hpp"
#include "duckdb/common/exception.hpp"
#include "duckdb/function/scalar_function.hpp"
#include "duckdb/function/table_function.hpp"
#include "duckdb/parser/parsed_data/create_scalar_function_info.hpp"
#include "duckdb/parser/parsed_data/create_table_function_info.hpp"
#include "duckdb/common/types/value.hpp"
#include "yyjson.hpp"

// OpenSSL linked through vcpkg
#include <openssl/opensslv.h>

// cpp-httplib for HTTP requests
#include <httplib.h>

namespace duckdb {
using namespace duckdb_yyjson;

// Bind data to store PostHog query results
struct PosthogQueryBindData : public TableFunctionData {
	string url;
	string project_id;
	string api_key;
	string hogql_query;

	// Store the query results
	vector<vector<Value>> results;
	vector<string> column_names;
	vector<LogicalType> column_types;

	idx_t row_count;
};

// Convert PostHog type string to DuckDB LogicalType
static LogicalType PosthogTypeToDuckDBType(const string &posthog_type) {
	// Remove Nullable() wrapper if present
	string base_type = posthog_type;
	if (base_type.find("Nullable(") == 0 && base_type.back() == ')') {
		base_type = base_type.substr(9, base_type.length() - 10);
	}

	// String types
	if (base_type == "String" || base_type == "LowCardinality(String)") {
		return LogicalType::VARCHAR;
	}

	// Unsigned integer types
	if (base_type == "UInt64") {
		return LogicalType::UBIGINT;
	} else if (base_type == "UInt32") {
		return LogicalType::UINTEGER;
	} else if (base_type == "UInt16") {
		return LogicalType::USMALLINT;
	} else if (base_type == "UInt8") {
		return LogicalType::UTINYINT;
	}

	// Signed integer types
	if (base_type == "Int64") {
		return LogicalType::BIGINT;
	} else if (base_type == "Int32") {
		return LogicalType::INTEGER;
	} else if (base_type == "Int16") {
		return LogicalType::SMALLINT;
	} else if (base_type == "Int8") {
		return LogicalType::TINYINT;
	}

	// Floating point types
	if (base_type == "Float64") {
		return LogicalType::DOUBLE;
	} else if (base_type == "Float32") {
		return LogicalType::FLOAT;
	}

	// Date/Time types - handle DateTime64 with any precision and timezone
	// Examples: DateTime, DateTime64(6), DateTime64(6, 'UTC')
	if (base_type == "DateTime" || base_type.find("DateTime64(") == 0) {
		return LogicalType::TIMESTAMP;
	} else if (base_type == "Date" || base_type == "Date32") {
		return LogicalType::DATE;
	}

	// Boolean
	if (base_type == "Bool" || base_type == "Boolean") {
		return LogicalType::BOOLEAN;
	}

	// UUID
	if (base_type == "UUID") {
		return LogicalType::VARCHAR;  // Treat UUID as VARCHAR
	}

	// Enum types - treat as VARCHAR
	// Examples: Enum8('value1' = 1, 'value2' = 2), Enum16(...)
	if (base_type.find("Enum8(") == 0 || base_type.find("Enum16(") == 0) {
		return LogicalType::VARCHAR;
	}

	// Array types - treat as VARCHAR (JSON representation)
	// Examples: Array(String), Array(Int32), Array(Enum8(...))
	if (base_type.find("Array(") == 0) {
		return LogicalType::VARCHAR;
	}

	// Tuple types - treat as VARCHAR (JSON representation)
	if (base_type.find("Tuple(") == 0) {
		return LogicalType::VARCHAR;
	}

	// Default to VARCHAR for unknown types
	return LogicalType::VARCHAR;
}

// Parse JSON value and convert to DuckDB Value
static Value ParseJsonValue(yyjson_val *json_val, const LogicalType &type) {
	if (!json_val || yyjson_is_null(json_val)) {
		return Value(type);  // NULL value
	}

	switch (type.id()) {
	case LogicalTypeId::VARCHAR:
		if (yyjson_is_str(json_val)) {
			return Value(yyjson_get_str(json_val));
		} else if (yyjson_is_num(json_val)) {
			return Value(to_string(yyjson_get_num(json_val)));
		}
		return Value(yyjson_val_write(json_val, 0, nullptr));

	case LogicalTypeId::BIGINT:
		if (yyjson_is_int(json_val)) {
			return Value::BIGINT(yyjson_get_sint(json_val));
		}
		return Value::BIGINT(0);

	case LogicalTypeId::UBIGINT:
		if (yyjson_is_uint(json_val)) {
			return Value::UBIGINT(yyjson_get_uint(json_val));
		}
		return Value::UBIGINT(0);

	case LogicalTypeId::INTEGER:
		if (yyjson_is_int(json_val)) {
			return Value::INTEGER((int32_t)yyjson_get_sint(json_val));
		}
		return Value::INTEGER(0);

	case LogicalTypeId::UINTEGER:
		if (yyjson_is_uint(json_val)) {
			return Value::UINTEGER((uint32_t)yyjson_get_uint(json_val));
		}
		return Value::UINTEGER(0);

	case LogicalTypeId::DOUBLE:
		if (yyjson_is_num(json_val)) {
			return Value::DOUBLE(yyjson_get_num(json_val));
		}
		return Value::DOUBLE(0.0);

	case LogicalTypeId::FLOAT:
		if (yyjson_is_num(json_val)) {
			return Value::FLOAT((float)yyjson_get_num(json_val));
		}
		return Value::FLOAT(0.0f);

	case LogicalTypeId::BOOLEAN:
		if (yyjson_is_bool(json_val)) {
			return Value::BOOLEAN(yyjson_get_bool(json_val));
		}
		return Value::BOOLEAN(false);

	case LogicalTypeId::SMALLINT:
		if (yyjson_is_int(json_val)) {
			return Value::SMALLINT((int16_t)yyjson_get_sint(json_val));
		}
		return Value::SMALLINT(0);

	case LogicalTypeId::USMALLINT:
		if (yyjson_is_uint(json_val)) {
			return Value::USMALLINT((uint16_t)yyjson_get_uint(json_val));
		}
		return Value::USMALLINT(0);

	case LogicalTypeId::TINYINT:
		if (yyjson_is_int(json_val)) {
			return Value::TINYINT((int8_t)yyjson_get_sint(json_val));
		}
		return Value::TINYINT(0);

	case LogicalTypeId::UTINYINT:
		if (yyjson_is_uint(json_val)) {
			return Value::UTINYINT((uint8_t)yyjson_get_uint(json_val));
		}
		return Value::UTINYINT(0);

	case LogicalTypeId::TIMESTAMP:
		// PostHog returns timestamps as ISO strings - use Value constructor with string
		if (yyjson_is_str(json_val)) {
			return Value(yyjson_get_str(json_val)).DefaultCastAs(LogicalType::TIMESTAMP);
		}
		return Value(type);  // NULL

	case LogicalTypeId::DATE:
		// PostHog returns dates as strings - use Value constructor with string
		if (yyjson_is_str(json_val)) {
			return Value(yyjson_get_str(json_val)).DefaultCastAs(LogicalType::DATE);
		}
		return Value(type);  // NULL

	default:
		// For complex types, convert to string
		if (yyjson_is_str(json_val)) {
			return Value(yyjson_get_str(json_val));
		}
		return Value(yyjson_val_write(json_val, 0, nullptr));
	}
}

// Bind function - validates inputs and fetches data from PostHog
static unique_ptr<FunctionData> PosthogQueryBind(ClientContext &context, TableFunctionBindInput &input,
                                                   vector<LogicalType> &return_types, vector<string> &names) {
	auto result = make_uniq<PosthogQueryBindData>();

	// Validate input parameters - accept either 1 parameter (query only) or 4 parameters (explicit config)
	if (input.inputs.size() == 1) {
		// Read from environment variables
		const char* env_host = std::getenv("POSTHOG_HOST");
		const char* env_project_id = std::getenv("POSTHOG_PROJECT_ID");
		const char* env_api_key = std::getenv("POSTHOG_API_KEY");

		if (!env_host || !env_project_id || !env_api_key) {
			throw BinderException("posthog_query requires either:\n"
			                      "  - 1 parameter (hogql_query) with POSTHOG_HOST, POSTHOG_PROJECT_ID, and POSTHOG_API_KEY env vars set, or\n"
			                      "  - 4 parameters: (url, project_id, api_key, hogql_query)");
		}

		result->url = string(env_host);
		result->project_id = string(env_project_id);
		result->api_key = string(env_api_key);
		result->hogql_query = input.inputs[0].GetValue<string>();
	} else if (input.inputs.size() == 4) {
		// Explicit parameters
		result->url = input.inputs[0].GetValue<string>();
		result->project_id = input.inputs[1].GetValue<string>();
		result->api_key = input.inputs[2].GetValue<string>();
		result->hogql_query = input.inputs[3].GetValue<string>();
	} else {
		throw BinderException("posthog_query requires either:\n"
		                      "  - 1 parameter (hogql_query) with POSTHOG_HOST, POSTHOG_PROJECT_ID, and POSTHOG_API_KEY env vars set, or\n"
		                      "  - 4 parameters: (url, project_id, api_key, hogql_query)");
	}

	// Parse URL to extract host and scheme
	string host = result->url;
	bool use_ssl = true;

	// Remove protocol if present
	if (host.find("https://") == 0) {
		host = host.substr(8);
		use_ssl = true;
	} else if (host.find("http://") == 0) {
		host = host.substr(7);
		use_ssl = false;
	}

	// Remove trailing slash
	if (!host.empty() && host.back() == '/') {
		host = host.substr(0, host.size() - 1);
	}

	// Make HTTP request to PostHog
	try {
		httplib::Client client(use_ssl ? ("https://" + host) : ("http://" + host));
		client.set_follow_location(true);

		// Escape quotes in the query
		size_t pos = 0;
		string escaped_query = result->hogql_query;
		while ((pos = escaped_query.find("\"", pos)) != string::npos) {
			escaped_query.replace(pos, 1, "\\\"");
			pos += 2;
		}
		request_body = "{\"query\":{\"kind\":\"HogQLQuery\",\"query\":\"" + escaped_query + "\"}}";

		string path = "/api/projects/" + result->project_id + "/query/";

		httplib::Headers headers = {
			{"Authorization", "Bearer " + result->api_key},
		};

		auto res = client.Post(path, headers, request_body, "application/json");

		if (!res) {
			throw IOException("HTTP request to PostHog failed: connection error");
		}

		if (res->status != 200) {
			throw IOException("HTTP request to PostHog failed with status " + to_string(res->status) +
			                  ": " + res->body);
		}

		// Parse JSON response
		yyjson_doc *doc = yyjson_read(res->body.c_str(), res->body.length(), 0);
		if (!doc) {
			throw IOException("Failed to parse PostHog JSON response");
		}

		yyjson_val *root = yyjson_doc_get_root(doc);

		// Extract columns
		yyjson_val *columns = yyjson_obj_get(root, "columns");
		if (!columns || !yyjson_is_arr(columns)) {
			yyjson_doc_free(doc);
			throw IOException("PostHog response missing 'columns' array");
		}

		// Extract types
		yyjson_val *types = yyjson_obj_get(root, "types");
		if (!types || !yyjson_is_arr(types)) {
			yyjson_doc_free(doc);
			throw IOException("PostHog response missing 'types' array");
		}

		// Extract results
		yyjson_val *results_arr = yyjson_obj_get(root, "results");
		if (!results_arr || !yyjson_is_arr(results_arr)) {
			yyjson_doc_free(doc);
			throw IOException("PostHog response missing 'results' array");
		}

		// Process columns and types
		size_t col_count = yyjson_arr_size(columns);
		size_t type_count = yyjson_arr_size(types);

		if (col_count != type_count) {
			yyjson_doc_free(doc);
			throw IOException("PostHog response: columns and types arrays have different sizes");
		}

		// Build schema using simple index-based access
		for (size_t i = 0; i < col_count; i++) {
			yyjson_val *col_val = yyjson_arr_get(columns, i);
			yyjson_val *type_val = yyjson_arr_get(types, i);

			// Convert to string (handle both string and other types)
			string col_name;
			string type_name;

			if (yyjson_is_str(col_val)) {
				col_name = yyjson_get_str(col_val);
			} else {
				// Fallback: convert to JSON string
				size_t len;
				char *json_str = yyjson_val_write(col_val, 0, &len);
				col_name = string(json_str ? json_str : "unknown");
				if (json_str) free(json_str);
			}

			// PostHog returns types as arrays: ["column_name", "type_string"]
			// We need to extract the second element
			if (yyjson_is_arr(type_val) && yyjson_arr_size(type_val) >= 2) {
				// Get the second element (index 1) which contains the actual type
				yyjson_val *actual_type = yyjson_arr_get(type_val, 1);
				if (yyjson_is_str(actual_type)) {
					type_name = yyjson_get_str(actual_type);
				} else {
					type_name = "String";
				}
			} else if (yyjson_is_str(type_val)) {
				type_name = yyjson_get_str(type_val);
			} else {
				// Fallback: convert to JSON string
				size_t len;
				char *json_str = yyjson_val_write(type_val, 0, &len);
				type_name = string(json_str ? json_str : "String");
				if (json_str) free(json_str);
			}

			result->column_names.push_back(col_name);
			LogicalType duck_type = PosthogTypeToDuckDBType(type_name);
			result->column_types.push_back(duck_type);

			names.push_back(col_name);
			return_types.push_back(duck_type);
		}

		// Process results using simple index-based access
		result->row_count = yyjson_arr_size(results_arr);

		for (size_t row_idx = 0; row_idx < result->row_count; row_idx++) {
			yyjson_val *row = yyjson_arr_get(results_arr, row_idx);

			if (!yyjson_is_arr(row)) {
				yyjson_doc_free(doc);
				throw IOException("PostHog response: result row is not an array");
			}

			vector<Value> row_values;
			size_t row_size = yyjson_arr_size(row);

			for (size_t col_idx = 0; col_idx < col_count && col_idx < row_size; col_idx++) {
				yyjson_val *val = yyjson_arr_get(row, col_idx);
				row_values.push_back(ParseJsonValue(val, result->column_types[col_idx]));
			}

			result->results.push_back(std::move(row_values));
		}

		yyjson_doc_free(doc);

	} catch (const std::exception &e) {
		throw IOException("PostHog query failed: " + string(e.what()));
	}

	return std::move(result);
}

// Local state for tracking which row we're on
struct PosthogQueryLocalState : public LocalTableFunctionState {
	idx_t current_row;

	PosthogQueryLocalState() : current_row(0) {
	}
};

static unique_ptr<LocalTableFunctionState> PosthogQueryInitLocal(ExecutionContext &context, TableFunctionInitInput &input,
                                                                   GlobalTableFunctionState *global_state) {
	return make_uniq<PosthogQueryLocalState>();
}

// Execute function - outputs the cached results
static void PosthogQueryExecute(ClientContext &context, TableFunctionInput &data, DataChunk &output) {
	auto &bind_data = data.bind_data->Cast<PosthogQueryBindData>();
	auto &local_state = data.local_state->Cast<PosthogQueryLocalState>();

	// Check if we're done
	if (local_state.current_row >= bind_data.row_count) {
		output.SetCardinality(0);
		return;
	}

	// Calculate how many rows to output
	idx_t remaining = bind_data.row_count - local_state.current_row;
	idx_t count = MinValue<idx_t>(remaining, STANDARD_VECTOR_SIZE);

	// Fill the output chunk
	for (idx_t col_idx = 0; col_idx < bind_data.column_types.size(); col_idx++) {
		auto &vec = output.data[col_idx];

		for (idx_t i = 0; i < count; i++) {
			idx_t row_idx = local_state.current_row + i;
			const auto &value = bind_data.results[row_idx][col_idx];
			vec.SetValue(i, value);
		}
	}

	output.SetCardinality(count);
	local_state.current_row += count;
}

static void LoadInternal(ExtensionLoader &loader) {
	// Register the posthog_query table function
	// Accepts either 1 argument (query with env vars) or 4 arguments (explicit config)
	TableFunction posthog_query_func(
		"posthog_query",
		{LogicalType::VARCHAR},
		PosthogQueryExecute,
		PosthogQueryBind
	);
	posthog_query_func.init_local = PosthogQueryInitLocal;
	posthog_query_func.varargs = LogicalType::VARCHAR;

	loader.RegisterFunction(posthog_query_func);
}

void PosthogExtension::Load(ExtensionLoader &loader) {
	LoadInternal(loader);
}

std::string PosthogExtension::Name() {
	return "posthog";
}

std::string PosthogExtension::Version() const {
#ifdef EXT_VERSION_POSTHOG
	return EXT_VERSION_POSTHOG;
#else
	return "0.1.0";
#endif
}

} // namespace duckdb

extern "C" {

DUCKDB_CPP_EXTENSION_ENTRY(posthog, loader) {
	duckdb::LoadInternal(loader);
}
}
