#include "fixture.h"

namespace
{
	int dispatched_impl() noexcept
	{
		return fixture::shared;
	}
}

extern "C"
{
	[[gnu::visibility("hidden")]] decltype(&dispatched_impl) fixture_resolve_dispatched() noexcept
	{
		return dispatched_impl;
	}
}

namespace fixture
{
	int counter;
	int seed = 7;
	[[gnu::weak]] int fallback = 3;
	const int table[4] = { 1, 2, 3, 4 };

	shape::~shape() noexcept = default;

	square::square(double side) noexcept : side_{ side }
	{}

	double square::area() const noexcept
	{
		return side_ * side_;
	}

	square::operator bool() const noexcept
	{
		return side_ > 0.0;
	}

	void* square::operator new(decltype(sizeof(0)) size)
	{
		return ::operator new(size);
	}

	void square::operator delete(void* ptr) noexcept
	{
		::operator delete(ptr);
	}

	square operator*(const square& lhs, double rhs) noexcept
	{
		return square{ lhs.area() * rhs };
	}

	int doubler::operator()(int value) const noexcept
	{
		return value * 2;
	}

	int add(int lhs, int rhs) noexcept
	{
		return lhs + rhs;
	}

	double add(double lhs, double rhs) noexcept
	{
		return lhs + rhs;
	}

	template <>
	int twice<int>(int value) noexcept
	{
		return value * 2;
	}

	template <typename T>
	T thrice(T value) noexcept
	{
		return value * 3;
	}

	template int thrice<int>(int) noexcept;

	int not_imported() noexcept
	{
		return 42;
	}

	[[gnu::ifunc("fixture_resolve_dispatched")]] int dispatched() noexcept;
}

extern "C" int versioned_answer() noexcept
{
	return 42;
}
