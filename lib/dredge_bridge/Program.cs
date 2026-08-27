// Vendored from AppleBoiy/dredge-se (dotnet/Program.cs), unmodified.
// https://github.com/AppleBoiy/dredge-se
// No LICENSE file was published in that repo at the time this was copied;
// check the upstream repo yourself if you plan to redistribute this file.
//
// This is the DREDGE save bridge: it loads the game's own compiled
// Assembly-CSharp.dll from your local install (via reflection) so it can
// deserialize/reserialize the .NET BinaryFormatter save file using the
// game's real types - that isn't reimplementable in pure Python.
// cedit invokes this as `dotnet <dll> <inspect|edit> <save> <managed-dir> [patch.json]`.
using System.Collections;
using System.Globalization;
using System.Reflection;
using System.Runtime.Loader;
using System.Runtime.Serialization.Formatters.Binary;
using System.Text.Json;
using System.Text.Json.Nodes;

AppContext.SetSwitch("System.Runtime.Serialization.EnableUnsafeBinaryFormatterSerialization", true);

var jsonOptions = new JsonSerializerOptions { WriteIndented = true };

try
{
    if (args.Length < 3)
        throw new ArgumentException("Usage: DredgeSaveBridge <inspect|edit> <save-path> <managed-dir> [patch-json-path], or reflect <pattern> <managed-dir>");

    var command = args[0];
    var managedDir = Path.GetFullPath(args[2]);

    if (!Directory.Exists(managedDir)) throw new DirectoryNotFoundException($"Game Managed directory not found: {managedDir}");

    AssemblyLoadContext.Default.Resolving += (_, name) =>
    {
        var candidate = Path.Combine(managedDir, name.Name + ".dll");
        return File.Exists(candidate) ? AssemblyLoadContext.Default.LoadFromAssemblyPath(candidate) : null;
    };

    var gameAssembly = AssemblyLoadContext.Default.LoadFromAssemblyPath(Path.Combine(managedDir, "Assembly-CSharp.dll"));

    if (command == "reflect")
    {
        var pattern = args[1];
        Console.WriteLine(JsonSerializer.Serialize(ReflectMembers(gameAssembly, pattern), jsonOptions));
        return;
    }

    var savePath = Path.GetFullPath(args[1]);
    if (!File.Exists(savePath)) throw new FileNotFoundException("Save file not found", savePath);

    object saveData;
#pragma warning disable SYSLIB0011
    using (var input = File.OpenRead(savePath))
        saveData = new BinaryFormatter().Deserialize(input);
#pragma warning restore SYSLIB0011

    if (command == "inspect")
    {
        Console.WriteLine(JsonSerializer.Serialize(Inspect(saveData, savePath), jsonOptions));
        return;
    }

    if (command != "edit" || args.Length < 4)
        throw new ArgumentException("Edit requires a patch JSON path");

    var patch = JsonNode.Parse(File.ReadAllText(args[3]))?.AsObject()
        ?? throw new InvalidDataException("Patch must be a JSON object");

    ApplyPatch(saveData, patch);

    var tempPath = savePath + ".dredge-editor-tmp";
    try
    {
#pragma warning disable SYSLIB0011
        using (var output = new FileStream(tempPath, FileMode.Create, FileAccess.Write, FileShare.None))
            new BinaryFormatter().Serialize(output, saveData);
#pragma warning restore SYSLIB0011

        // Prove the generated file can be deserialized before replacing anything.
#pragma warning disable SYSLIB0011
        using (var verify = File.OpenRead(tempPath))
            _ = new BinaryFormatter().Deserialize(verify);
#pragma warning restore SYSLIB0011

        var backupDir = Path.Combine(Path.GetDirectoryName(savePath)!, "dredge-editor-backups");
        Directory.CreateDirectory(backupDir);
        var stamp = DateTime.UtcNow.ToString("yyyyMMdd-HHmmss-fff", CultureInfo.InvariantCulture);
        var backupPath = Path.Combine(backupDir, Path.GetFileName(savePath) + "." + stamp + ".bak");
        File.Copy(savePath, backupPath, overwrite: false);
        File.Move(tempPath, savePath, overwrite: true);

        Console.WriteLine(JsonSerializer.Serialize(new {
            ok = true,
            backupPath,
            save = Inspect(saveData, savePath)
        }, jsonOptions));
    }
    finally
    {
        if (File.Exists(tempPath)) File.Delete(tempPath);
    }
}
catch (Exception ex)
{
    Console.Error.WriteLine(JsonSerializer.Serialize(new {
        ok = false,
        error = ex.GetBaseException().Message,
        type = ex.GetBaseException().GetType().Name
    }, jsonOptions));
    Environment.ExitCode = 1;
}

static object ReflectMembers(Assembly assembly, string pattern)
{
    const BindingFlags flags = BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
    var comparison = StringComparison.OrdinalIgnoreCase;
    return assembly.GetTypes()
        .SelectMany(type => type.GetMembers(flags)
            .Where(member => type.FullName!.Contains(pattern, comparison) || member.Name.Contains(pattern, comparison))
            .Select(member => new
            {
                type = type.FullName,
                kind = member.MemberType.ToString(),
                name = member.Name,
                signature = member.ToString()
            }))
        .OrderBy(item => item.type)
        .ThenBy(item => item.name)
        .ToArray();
}

static object Inspect(object saveData, string path)
{
    var type = saveData.GetType();
    return new
    {
        ok = true,
        path,
        fileName = Path.GetFileName(path),
        size = new FileInfo(path).Length,
        modifiedAt = File.GetLastWriteTimeUtc(path),
        saveType = type.FullName,
        lastSavedTime = ReadMember(saveData, "lastSavedTime")?.ToString(),
        version = ReadMember(saveData, "version")?.ToString(),
        dockId = ReadMember(saveData, "dockId")?.ToString(),
        dockSlotIndex = ReadMember(saveData, "dockSlotIndex"),
        variables = new
        {
            decimals = DictionaryToObject(ReadMember(saveData, "decimalVariables")),
            integers = DictionaryToObject(ReadMember(saveData, "intVariables")),
            floats = DictionaryToObject(ReadMember(saveData, "floatVariables")),
            strings = DictionaryToObject(ReadMember(saveData, "stringVariables")),
            booleans = DictionaryToObject(ReadMember(saveData, "boolVariables"))
        },
        collections = new
        {
            visitedNodes = CollectionCount(ReadMember(saveData, "visitedNodes")),
            ownedItems = CollectionCount(ReadMember(saveData, "ownedNonSpatialItems")),
            quests = CollectionCount(ReadMember(saveData, "questEntries")),
            researchedItems = CollectionCount(ReadMember(saveData, "itemIdsResearched")),
            upgrades = CollectionCount(ReadMember(saveData, "upgradeIdsOwned")),
            caughtFishSpecies = CollectionCount(ReadMember(saveData, "caughtFishCounts"))
        },
        inventory = InspectGrid(ReadMember(saveData, "Inventory")),
        storage = InspectGrid(ReadMember(saveData, "Storage")),
        overflowStorage = InspectGrid(ReadMember(saveData, "OverflowStorage")),
        nonSpatialItems = InspectNonSpatialItems(ReadMember(saveData, "ownedNonSpatialItems"))
    };
}

static object InspectGrid(object? grid)
{
    if (grid is null) return new { rows = 0, columns = 0, items = Array.Empty<object>() };
    var cells = ReadMember(grid, "grid") as Array;
    var items = ReadMember(grid, "spatialItems") as IEnumerable;
    return new
    {
        rows = cells?.Rank == 2 ? cells.GetLength(0) : 0,
        columns = cells?.Rank == 2 ? cells.GetLength(1) : 0,
        items = items?.Cast<object>().Select((item, index) => InspectItem(item, index)).ToArray()
            ?? Array.Empty<object>()
    };
}

static object InspectItem(object item, int index)
{
    var values = new Dictionary<string, object?>(StringComparer.Ordinal);
    for (var type = item.GetType(); type is not null; type = type.BaseType)
    {
        foreach (var field in type.GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
        {
            if ((field.Attributes & FieldAttributes.NotSerialized) != 0 || field.Name.StartsWith("On", StringComparison.Ordinal)) continue;
            var value = field.GetValue(item);
            if (value is null || value is string || value.GetType().IsPrimitive || value is decimal)
                values.TryAdd(field.Name, value);
        }
    }
    return new { index, runtimeType = item.GetType().FullName, values };
}

static object[] InspectNonSpatialItems(object? value)
{
    if (value is not IEnumerable items) return Array.Empty<object>();
    return items.Cast<object>().Select((item, index) => InspectItem(item, index)).ToArray();
}

static object? ReadMember(object target, string name)
{
    const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
    var type = target.GetType();
    return type.GetField(name, flags)?.GetValue(target)
        ?? type.GetProperty(name, flags)?.GetValue(target);
}

static Dictionary<string, object?> DictionaryToObject(object? value)
{
    var result = new Dictionary<string, object?>(StringComparer.Ordinal);
    if (value is not IDictionary dictionary) return result;
    foreach (DictionaryEntry entry in dictionary)
        if (entry.Key is string key) result[key] = entry.Value;
    return result;
}

static int CollectionCount(object? value) => value switch
{
    ICollection collection => collection.Count,
    _ => 0
};

static void ApplyPatch(object saveData, JsonObject patch)
{
    var hasChanges = false;
    if (patch["variables"] is JsonObject groups)
    {
        ApplyVariablePatch(saveData, groups);
        hasChanges = groups.Count > 0;
    }
    else if (patch.ContainsKey("variables"))
        throw new InvalidDataException("Patch.variables must be an object");

    if (patch["inventoryOps"] is JsonArray operations)
    {
        ApplyInventoryOperations(saveData, operations);
        hasChanges |= operations.Count > 0;
    }
    else if (patch.ContainsKey("inventoryOps"))
        throw new InvalidDataException("Patch.inventoryOps must be an array");

    if (!hasChanges) throw new InvalidDataException("Patch contains no changes");
}

static void ApplyVariablePatch(object saveData, JsonObject groups)
{

    var mappings = new Dictionary<string, (string Member, Type Type)>
    {
        ["decimals"] = ("decimalVariables", typeof(decimal)),
        ["integers"] = ("intVariables", typeof(int)),
        ["floats"] = ("floatVariables", typeof(float)),
        ["strings"] = ("stringVariables", typeof(string)),
        ["booleans"] = ("boolVariables", typeof(bool))
    };

    foreach (var group in groups)
    {
        if (!mappings.TryGetValue(group.Key, out var mapping) || group.Value is not JsonObject values)
            throw new InvalidDataException($"Unknown or invalid variable group: {group.Key}");

        var target = ReadMember(saveData, mapping.Member) as IDictionary
            ?? throw new InvalidDataException($"Save is missing {mapping.Member}");

        foreach (var item in values)
        {
            if (!target.Contains(item.Key))
                throw new InvalidDataException($"Unknown {group.Key} key: {item.Key}");
            target[item.Key] = ConvertNode(item.Value, mapping.Type, item.Key);
        }
    }
}

static void ApplyInventoryOperations(object saveData, JsonArray operations)
{
    if (operations.Count > 100) throw new InvalidDataException("At most 100 inventory operations are allowed");
    foreach (var node in operations)
    {
        if (node is not JsonObject operation) throw new InvalidDataException("Each inventory operation must be an object");
        var action = RequiredString(operation, "action");
        if (action == "spawn")
        {
            var spawnTarget = GetItemList(saveData, RequiredString(operation, "target"));
            var runtimeType = RequiredString(operation, "runtimeType");
            if (runtimeType is not ("SpatialItemInstance" or "FishItemInstance"))
                throw new InvalidDataException($"Unsupported spawn runtime type: {runtimeType}");
            var instanceType = saveData.GetType().Assembly.GetType(runtimeType)
                ?? throw new InvalidDataException($"Game type not found: {runtimeType}");
            var spawned = Activator.CreateInstance(instanceType)
                ?? throw new InvalidDataException($"Could not create {runtimeType}");
            SetMember(spawned, "id", RequiredString(operation, "id"));
            SetMember(spawned, "x", RequiredInt(operation, "x"));
            SetMember(spawned, "y", RequiredInt(operation, "y"));
            SetMember(spawned, "z", NormalizeRotation(RequiredInt(operation, "z")));
            SetMember(spawned, "seen", true);
            SetMember(spawned, "durability", 1f);
            SetMember(spawned, "isOnDamagedCell", false);
            if (runtimeType == "FishItemInstance")
            {
                SetMember(spawned, "freshness", 1f);
                SetMember(spawned, "size", 1f);
                SetMember(spawned, "isInfected", false);
            }
            spawnTarget.Add(spawned);
            continue;
        }
        var container = RequiredString(operation, "container");
        var index = RequiredInt(operation, "index");
        var expectedId = RequiredString(operation, "id");
        var source = GetItemList(saveData, container);
        if (index < 0 || index >= source.Count) throw new InvalidDataException($"{container} item index {index} is out of range; reload the save");
        var item = source[index] ?? throw new InvalidDataException($"{container} item index {index} is empty");
        var actualId = ReadMember(item, "id") as string;
        if (!StringComparer.Ordinal.Equals(expectedId, actualId))
            throw new InvalidDataException($"{container} item changed from {expectedId} to {actualId}; reload the save");

        if (action == "move")
        {
            if (container == "nonSpatialItems") throw new InvalidDataException("Non-spatial items cannot be placed on a grid");
            SetMember(item, "x", RequiredInt(operation, "x"));
            SetMember(item, "y", RequiredInt(operation, "y"));
            SetMember(item, "z", NormalizeRotation(RequiredInt(operation, "z")));
            SetMember(item, "isOnDamagedCell", false);
            continue;
        }
        if (action == "remove")
        {
            source.RemoveAt(index);
            continue;
        }
        if (action != "duplicate") throw new InvalidDataException($"Unknown inventory action: {action}");

        var targetName = operation["target"]?.GetValue<string>() ?? "overflowStorage";
        var target = GetItemList(saveData, targetName);
        var copy = CloneSerializable(item);
        if (container != "nonSpatialItems")
        {
            if (targetName == "nonSpatialItems") throw new InvalidDataException("Spatial items cannot be added to non-spatial items");
            SetMember(copy, "x", OptionalInt(operation, "x", 0));
            SetMember(copy, "y", OptionalInt(operation, "y", target.Count));
            SetMember(copy, "z", NormalizeRotation(OptionalInt(operation, "z", 0)));
            SetMember(copy, "isOnDamagedCell", false);
        }
        else if (targetName != "nonSpatialItems")
            throw new InvalidDataException("Non-spatial items can only be copied to non-spatial items");
        target.Add(copy);
    }
}

static IList GetItemList(object saveData, string container)
{
    object? value = container switch
    {
        "inventory" => ReadMember(ReadMember(saveData, "Inventory")!, "spatialItems"),
        "storage" => ReadMember(ReadMember(saveData, "Storage")!, "spatialItems"),
        "overflowStorage" => ReadMember(ReadMember(saveData, "OverflowStorage")!, "spatialItems"),
        "nonSpatialItems" => ReadMember(saveData, "ownedNonSpatialItems"),
        _ => throw new InvalidDataException($"Unknown item container: {container}")
    };
    return value as IList ?? throw new InvalidDataException($"Save is missing item container {container}");
}

static object CloneSerializable(object item)
{
#pragma warning disable SYSLIB0011
    using var stream = new MemoryStream();
    var formatter = new BinaryFormatter();
    formatter.Serialize(stream, item);
    stream.Position = 0;
    return formatter.Deserialize(stream);
#pragma warning restore SYSLIB0011
}

static void SetMember(object target, string name, object value)
{
    const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
    var field = target.GetType().GetField(name, flags) ?? target.GetType().BaseType?.GetField(name, flags);
    if (field is null) throw new InvalidDataException($"{target.GetType().Name} is missing {name}");
    field.SetValue(target, value);
}

static string RequiredString(JsonObject value, string key)
{
    var result = value[key]?.GetValue<string>();
    return string.IsNullOrWhiteSpace(result) ? throw new InvalidDataException($"Inventory operation requires {key}") : result;
}

static int RequiredInt(JsonObject value, string key) => value[key]?.GetValue<int>()
    ?? throw new InvalidDataException($"Inventory operation requires {key}");
static int OptionalInt(JsonObject value, string key, int fallback) => value[key]?.GetValue<int>() ?? fallback;
static int NormalizeRotation(int value) => value switch
{
    0 or 90 or 180 or 270 => value,
    _ => throw new InvalidDataException("Item rotation must be 0, 90, 180, or 270")
};

static object ConvertNode(JsonNode? node, Type type, string key)
{
    try
    {
        if (type == typeof(string)) return node?.GetValue<string>() ?? "";
        if (type == typeof(bool)) return node!.GetValue<bool>();
        if (type == typeof(int)) return node!.GetValue<int>();
        if (type == typeof(float)) return node!.GetValue<float>();
        if (type == typeof(decimal)) return node!.GetValue<decimal>();
    }
    catch (Exception ex)
    {
        throw new InvalidDataException($"Invalid value for {key}: expected {type.Name}", ex);
    }
    throw new InvalidDataException($"Unsupported value type for {key}");
}
