#include "fixture.h"

namespace fixture
{
	int counter;
	int seed = 7;

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

	int not_imported() noexcept
	{
		return 42;
	}
}

extern "C" int versioned_answer() noexcept
{
	return 42;
}
